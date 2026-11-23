// Cuidadores (Etapa 5, RF20–RF22).
// Gestion de vinculos paciente–cuidador desde la web.
//
// Flujo:
// 1. El paciente crea una invitacion y recibe el codigo UNA SOLA
//    VEZ (caduca en 15 minutos). Lo comparte con su cuidador por
//    el canal que quiera; el codigo nunca se vuelve a mostrar.
// 2. El cuidador, ya registrado, presenta el codigo en «Soy
//    cuidador de» y vincula su identidad. El vinculo sigue
//    INVITADO.
// 3. El paciente acepta explicitamente y fija los permisos: el
//    vinculo pasa a ACTIVO. Sin esa aceptacion, el cuidador no ve
//    nada.
// 4. El paciente cambia permisos o revoca en cualquier momento;
//    la revocacion es inmediata y definitiva.
// 5. La auditoria muestra quien hizo que sobre los datos del
//    paciente (RF22).
//
// Los 8 permisos son independientes y empiezan en False.
// Gestionar exige poder ver: al marcar un permiso de gestion se
// marca su permiso de lectura, y al quitar la lectura se quita
// la gestion. El cuidador nunca puede confirmar ni posponer
// tomas: no existe ese permiso.

import { useEffect, useState } from "react";
import { ApiError } from "../services/api";
import {
  EMPTY_PERMISSIONS,
  PERMISSION_LABELS,
  acceptCaregiverCode,
  acceptCaregiverLink,
  getCaregiverAudit,
  inviteCaregiver,
  listCaregiverLinks,
  permissionsOf,
  revokeCaregiverLink,
  updateCaregiverPermissions,
  type CaregiverAuditEntry,
  type CaregiverAuditPage,
  type CaregiverLink,
  type CaregiverLinks,
  type CaregiverPermissions,
} from "../services/caregivers";
import ApiErrorCard from "../components/ApiErrorCard";
import { formatDate } from "../utils/user";

type PageState =
  | { kind: "loading" }
  | { kind: "ready"; links: CaregiverLinks; audit: CaregiverAuditPage }
  | { kind: "error"; error: ApiError };

const PERMISSION_LABEL_BY_KEY: Record<string, string> = Object.fromEntries(
  PERMISSION_LABELS.map((p) => [p.key, p.label]),
);

function withConsistency(
  perms: CaregiverPermissions,
  key: keyof CaregiverPermissions,
  value: boolean,
): CaregiverPermissions {
  const next = { ...perms, [key]: value };
  if (key === "perm_manage_medications" && value) {
    next.perm_view_medications = true;
  }
  if (key === "perm_view_medications" && !value) {
    next.perm_manage_medications = false;
  }
  if (key === "perm_manage_schedules" && value) {
    next.perm_view_schedules = true;
  }
  if (key === "perm_view_schedules" && !value) {
    next.perm_manage_schedules = false;
  }
  return next;
}

function PermissionsForm({
  value,
  onChange,
  disabled,
}: {
  value: CaregiverPermissions;
  onChange: (next: CaregiverPermissions) => void;
  disabled: boolean;
}) {
  return (
    <div className="perm-list">
      {PERMISSION_LABELS.map((perm) => (
        <label key={perm.key} className="perm-row">
          <input
            type="checkbox"
            checked={value[perm.key]}
            disabled={disabled}
            onChange={(event) =>
              onChange(withConsistency(value, perm.key, event.target.checked))
            }
          />
          <span>
            <span className="perm-label">{perm.label}</span>
            <span className="perm-hint">{perm.hint}</span>
          </span>
        </label>
      ))}
    </div>
  );
}

function auditLabel(entry: CaregiverAuditEntry): string {
  const who = entry.caregiver_name ?? "Sin identificar";
  const permission =
    entry.details && typeof entry.details.permission === "string"
      ? PERMISSION_LABEL_BY_KEY[entry.details.permission] ??
        entry.details.permission
      : null;
  switch (entry.action) {
    case "INVITE_CREATED":
      return "Creaste una invitación";
    case "INVITE_ACCEPTED":
      return `${who} aceptó la invitación`;
    case "INVITE_CODE_INVALIDATED":
      return "El código de invitación se invalidó por intentos fallidos";
    case "PERMISSION_GRANTED":
      return `${who} recibió el permiso «${permission ?? "desconocido"}»`;
    case "PERMISSION_REVOKED":
      return `${who} perdió el permiso «${permission ?? "desconocido"}»`;
    case "REVOKED":
      return `${who} dejó de ser tu cuidador`;
    case "ACCESS_DENIED":
      return `${who} intentó una acción sin permiso`;
    default:
      return entry.action;
  }
}

function statusBadge(link: CaregiverLink) {
  if (link.status === "ACTIVO") {
    return <span className="badge badge-done">Activo</span>;
  }
  if (link.status === "INVITADO") {
    return <span className="badge badge-pending">Invitado</span>;
  }
  return <span className="badge">Revocado</span>;
}

export default function CaregiversPage() {
  const [state, setState] = useState<PageState>({ kind: "loading" });
  const [success, setSuccess] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [inviteCode, setInviteCode] = useState<string | null>(null);
  const [inviting, setInviting] = useState(false);
  const [codeInput, setCodeInput] = useState("");
  const [linkingCode, setLinkingCode] = useState(false);
  const [acceptingId, setAcceptingId] = useState<number | null>(null);
  const [acceptPerms, setAcceptPerms] = useState<CaregiverPermissions>(
    EMPTY_PERMISSIONS,
  );
  const [busy, setBusy] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editPerms, setEditPerms] = useState<CaregiverPermissions>(
    EMPTY_PERMISSIONS,
  );
  const [revokeId, setRevokeId] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);

  async function load() {
    setState({ kind: "loading" });
    try {
      const [links, audit] = await Promise.all([
        listCaregiverLinks(),
        getCaregiverAudit(),
      ]);
      setState({ kind: "ready", links, audit });
    } catch (caught) {
      setState({
        kind: "error",
        error:
          caught instanceof ApiError
            ? caught
            : new ApiError(0, "No se pudieron cargar los cuidadores."),
      });
    }
  }

  useEffect(() => {
    void load();
  }, []);

  function fail(caught: unknown, fallback: string) {
    setActionError(
      caught instanceof ApiError ? caught.message : fallback,
    );
  }

  async function handleInvite() {
    setInviting(true);
    setSuccess(null);
    setActionError(null);
    setInviteCode(null);
    try {
      const invite = await inviteCaregiver();
      setInviteCode(invite.invite_code);
      setCopied(false);
      setSuccess(
        "Invitación creada. Comparte el código con tu cuidador.",
      );
      await load();
    } catch (caught) {
      fail(caught, "No se pudo crear la invitación.");
    } finally {
      setInviting(false);
    }
  }

  async function handleCopyCode() {
    if (!inviteCode) {
      return;
    }
    try {
      await navigator.clipboard.writeText(inviteCode);
      setCopied(true);
    } catch {
      // Sin portapapeles (navegador sin permiso): el codigo sigue
      // visible en el campo de solo lectura para copiarlo a mano.
      setCopied(false);
    }
  }

  async function handleLinkCode() {
    const code = codeInput.trim().toUpperCase();
    if (code.length !== 10) {
      setActionError("El código tiene 10 caracteres.");
      return;
    }
    setLinkingCode(true);
    setSuccess(null);
    setActionError(null);
    try {
      await acceptCaregiverCode(code);
      setCodeInput("");
      setSuccess(
        "Tu identidad quedó vinculada. El paciente debe aceptar la invitación para activarla.",
      );
      await load();
    } catch (caught) {
      fail(caught, "No se pudo vincular el código.");
    } finally {
      setLinkingCode(false);
    }
  }

  async function handleAccept(link: CaregiverLink) {
    setBusy(true);
    setSuccess(null);
    setActionError(null);
    try {
      await acceptCaregiverLink(link.id, acceptPerms);
      setAcceptingId(null);
      setAcceptPerms(EMPTY_PERMISSIONS);
      setSuccess(
        `«${link.caregiver_name ?? "Tu cuidador"}» ya es tu cuidador.`,
      );
      await load();
    } catch (caught) {
      fail(caught, "No se pudo aceptar la invitación.");
    } finally {
      setBusy(false);
    }
  }

  async function handleSavePermissions(link: CaregiverLink) {
    setBusy(true);
    setSuccess(null);
    setActionError(null);
    try {
      await updateCaregiverPermissions(link.id, editPerms);
      setEditingId(null);
      setSuccess("Permisos actualizados.");
      await load();
    } catch (caught) {
      fail(caught, "No se pudieron actualizar los permisos.");
    } finally {
      setBusy(false);
    }
  }

  async function handleRevoke(link: CaregiverLink) {
    setBusy(true);
    setSuccess(null);
    setActionError(null);
    try {
      await revokeCaregiverLink(link.id);
      setRevokeId(null);
      setEditingId(null);
      setSuccess("Vínculo revocado. El historial se conserva.");
      await load();
    } catch (caught) {
      fail(caught, "No se pudo revocar el vínculo.");
    } finally {
      setBusy(false);
    }
  }

  if (state.kind === "loading") {
    return (
      <div>
        <div className="page-head">
          <h2>Cuidadores</h2>
        </div>
        <p className="hint">Cargando tus cuidadores…</p>
      </div>
    );
  }

  if (state.kind === "error") {
    return (
      <div>
        <div className="page-head">
          <h2>Cuidadores</h2>
        </div>
        <ApiErrorCard error={state.error} onRetry={() => load()} />
      </div>
    );
  }

  const { links, audit } = state;
  const pendingAsPatient = links.as_patient.filter(
    (link) => link.status === "INVITADO",
  );
  const activeAsPatient = links.as_patient.filter(
    (link) => link.status === "ACTIVO",
  );
  const revokedAsPatient = links.as_patient.filter(
    (link) => link.status === "REVOCADO",
  );

  return (
    <div>
      <div className="page-head">
        <h2>Cuidadores</h2>
      </div>
      <p className="hint">
        Un cuidador es alguien de tu confianza que puede ver tus
        medicamentos, tratamientos y tomas, y recibir avisos si no
        confirmas una toma. Tú decides qué puede ver y hacer, y
        puedes revocarlo en cualquier momento. Un cuidador nunca
        puede confirmar ni posponer tomas por ti.
      </p>

      {success ? <p className="success-box">{success}</p> : null}
      {actionError ? <p className="error">{actionError}</p> : null}

      <section className="card">
        <h2>Mis cuidadores</h2>
        <p>
          Invita a un cuidador con un código de un solo uso. El
          cuidador debe tener cuenta en DosisAlerta y presentar el
          código; después tú aceptas la invitación y eliges sus
          permisos.
        </p>
        <button
          type="button"
          className="btn-primary"
          disabled={inviting}
          onClick={() => void handleInvite()}
        >
          {inviting ? "Creando invitación…" : "Invitar cuidador"}
        </button>

        {inviteCode ? (
          <div className="confirm-box" style={{ marginTop: "1rem" }}>
            <p>
              <strong>Código de invitación (se muestra una sola vez):</strong>
            </p>
            <p
              style={{
                fontSize: "1.5rem",
                letterSpacing: "0.2em",
                fontWeight: 700,
                margin: "0.5rem 0",
              }}
            >
              {inviteCode}
            </p>
            <p>
              Caduca en 15 minutos y no se volverá a mostrar. Si
              caduca, crea otra invitación.
            </p>
            <div className="confirm-actions">
              <button
                type="button"
                className="btn-primary"
                onClick={() => void handleCopyCode()}
              >
                {copied ? "Copiado" : "Copiar código"}
              </button>
            </div>
          </div>
        ) : null}

        {pendingAsPatient.length === 0 &&
        activeAsPatient.length === 0 &&
        revokedAsPatient.length === 0 ? (
          <p className="hint" style={{ marginTop: "1rem" }}>
            Aún no tienes cuidadores. Invita a alguien de tu
            confianza para que te acompañe.
          </p>
        ) : null}

        {pendingAsPatient.map((link) => (
          <div key={link.id} className="caregiver-block">
            <div className="med-item">
              <div>
                <p className="med-name">
                  {link.caregiver_name ?? "Cuidador sin identificar"}
                </p>
                <p className="med-meta">
                  {link.caregiver_email ?? "Esperando a que presente el código"}
                  {link.invite_expires_at
                    ? ` · expira ${formatDate(link.invite_expires_at)}`
                    : ""}
                </p>
              </div>
              {statusBadge(link)}
            </div>
            {link.caregiver_user_id !== null ? (
              acceptingId === link.id ? (
                <div style={{ marginTop: "0.75rem" }}>
                  <p>
                    Elige qué podrá ver y hacer{" "}
                    {link.caregiver_name ?? "tu cuidador"}:
                  </p>
                  <PermissionsForm
                    value={acceptPerms}
                    onChange={setAcceptPerms}
                    disabled={busy}
                  />
                  <div className="confirm-actions" style={{ marginTop: "0.75rem" }}>
                    <button
                      type="button"
                      className="btn-primary"
                      disabled={busy}
                      onClick={() => void handleAccept(link)}
                    >
                      {busy ? "Aceptando…" : "Aceptar y activar"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      disabled={busy}
                      onClick={() => {
                        setAcceptingId(null);
                        setAcceptPerms(EMPTY_PERMISSIONS);
                      }}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : (
                <div className="confirm-actions" style={{ marginTop: "0.75rem" }}>
                  <button
                    type="button"
                    className="btn-primary"
                    onClick={() => {
                      setAcceptingId(link.id);
                      setAcceptPerms(EMPTY_PERMISSIONS);
                    }}
                  >
                    Aceptar invitación
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setRevokeId(link.id)}
                  >
                    Revocar
                  </button>
                </div>
              )
            ) : (
              <p className="hint">
                El cuidador aún no ha presentado el código. Cuando lo
                haga, podrás aceptar la invitación y elegir sus
                permisos.
              </p>
            )}
            {revokeId === link.id ? (
              <div className="confirm-box">
                <p>
                  ¿Revocar esta invitación? El código dejará de
                  funcionar y no se podrá reactivar.
                </p>
                <div className="confirm-actions">
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={busy}
                    onClick={() => void handleRevoke(link)}
                  >
                    {busy ? "Revocando…" : "Sí, revocar"}
                  </button>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => setRevokeId(null)}
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ))}

        {activeAsPatient.map((link) => (
          <div key={link.id} className="caregiver-block">
            <div className="med-item">
              <div>
                <p className="med-name">{link.caregiver_name}</p>
                <p className="med-meta">
                  {link.caregiver_email}
                  {link.accepted_at
                    ? ` · desde ${formatDate(link.accepted_at)}`
                    : ""}
                </p>
              </div>
              {statusBadge(link)}
            </div>
            {editingId === link.id ? (
              <div style={{ marginTop: "0.75rem" }}>
                <PermissionsForm
                  value={editPerms}
                  onChange={setEditPerms}
                  disabled={busy}
                />
                <div className="confirm-actions" style={{ marginTop: "0.75rem" }}>
                  <button
                    type="button"
                    className="btn-primary"
                    disabled={busy}
                    onClick={() => void handleSavePermissions(link)}
                  >
                    {busy ? "Guardando…" : "Guardar permisos"}
                  </button>
                  <button
                    type="button"
                    className="btn-ghost"
                    disabled={busy}
                    onClick={() => setEditingId(null)}
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ marginTop: "0.5rem" }}>
                <p className="hint">
                  Permisos:{" "}
                  {PERMISSION_LABELS.filter(
                    (perm) => permissionsOf(link)[perm.key],
                  )
                    .map((perm) => perm.label)
                    .join(", ") || "ninguno"}
                </p>
                <div className="confirm-actions">
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => {
                      setEditingId(link.id);
                      setEditPerms(permissionsOf(link));
                    }}
                  >
                    Cambiar permisos
                  </button>
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setRevokeId(link.id)}
                  >
                    Revocar acceso
                  </button>
                </div>
              </div>
            )}
            {revokeId === link.id ? (
              <div className="confirm-box">
                <p>
                  ¿Revocar el acceso de «{link.caregiver_name}»? Dejará
                  de ver tus datos de inmediato. El historial se
                  conserva.
                </p>
                <div className="confirm-actions">
                  <button
                    type="button"
                    className="btn-danger"
                    disabled={busy}
                    onClick={() => void handleRevoke(link)}
                  >
                    {busy ? "Revocando…" : "Sí, revocar"}
                  </button>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => setRevokeId(null)}
                  >
                    Cancelar
                  </button>
                </div>
              </div>
            ) : null}
          </div>
        ))}

        {revokedAsPatient.length > 0 ? (
          <div style={{ marginTop: "1rem" }}>
            <h3>Revocados</h3>
            {revokedAsPatient.map((link) => (
              <p key={link.id} className="hint">
                {link.caregiver_name ?? "Cuidador sin identificar"}
                {link.revoked_at
                  ? ` · revocado el ${formatDate(link.revoked_at)}`
                  : ""}
              </p>
            ))}
          </div>
        ) : null}
      </section>

      <section className="card">
        <h2>Soy cuidador de</h2>
        <p>
          Si alguien te compartió un código de invitación, preséntalo
          aquí para vincular tu identidad. Después, esa persona debe
          aceptar la invitación y elegir tus permisos.
        </p>
        <div className="field-row">
          <div className="field">
            <label className="field-label" htmlFor="caregiver-code">
              Código de invitación
            </label>
            <input
              id="caregiver-code"
              type="text"
              value={codeInput}
              maxLength={10}
              autoComplete="off"
              autoCapitalize="characters"
              placeholder="10 caracteres"
              onChange={(event) => setCodeInput(event.target.value)}
            />
          </div>
        </div>
        <div className="confirm-actions" style={{ marginTop: "0.75rem" }}>
          <button
            type="button"
            className="btn-primary"
            disabled={linkingCode || codeInput.trim().length === 0}
            onClick={() => void handleLinkCode()}
          >
            {linkingCode ? "Vinculando…" : "Vincularme como cuidador"}
          </button>
        </div>
        {links.as_caregiver.length === 0 ? (
          <p className="hint" style={{ marginTop: "1rem" }}>
            No eres cuidador de nadie todavía.
          </p>
        ) : (
          links.as_caregiver.map((link) => (
            <div key={link.id} className="caregiver-block">
              <div className="med-item">
                <div>
                  <p className="med-name">{link.patient_name}</p>
                  <p className="med-meta">
                    {link.status === "ACTIVO"
                      ? `Tus permisos: ${PERMISSION_LABELS.filter(
                          (perm) => permissionsOf(link)[perm.key],
                        )
                          .map((perm) => perm.label)
                          .join(", ") || "ninguno"}`
                      : link.status === "INVITADO"
                        ? "Esperando la aceptación del paciente"
                        : `Revocado${link.revoked_at ? ` el ${formatDate(link.revoked_at)}` : ""}`}
                  </p>
                </div>
                {statusBadge(link)}
              </div>
              {link.status !== "REVOCADO" ? (
                <div className="confirm-actions" style={{ marginTop: "0.5rem" }}>
                  <button
                    type="button"
                    className="btn-danger"
                    onClick={() => setRevokeId(link.id)}
                  >
                    Dejar de ser cuidador
                  </button>
                </div>
              ) : null}
              {revokeId === link.id ? (
                <div className="confirm-box">
                  <p>
                    ¿Dejar de ser cuidador de «{link.patient_name}»? Ya
                    no verás sus datos.
                  </p>
                  <div className="confirm-actions">
                    <button
                      type="button"
                      className="btn-danger"
                      disabled={busy}
                      onClick={() => void handleRevoke(link)}
                    >
                      {busy ? "Revocando…" : "Sí, dejar de ser cuidador"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      onClick={() => setRevokeId(null)}
                    >
                      Cancelar
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ))
        )}
      </section>

      <section className="card">
        <h2>Quién ha hecho qué con tus datos</h2>
        {audit.items.length === 0 ? (
          <p className="hint">
            Aún no hay acciones de cuidadores sobre tus datos.
          </p>
        ) : (
          <ul className="upcoming-list">
            {audit.items.map((entry) => (
              <li key={entry.id} className="upcoming-item">
                <div>
                  <p className="med-name">{auditLabel(entry)}</p>
                  <p className="med-meta">{formatDate(entry.created_at)}</p>
                </div>
                <span
                  className={
                    entry.result === "OK"
                      ? "badge badge-done"
                      : "badge badge-pending"
                  }
                >
                  {entry.result === "OK" ? "OK" : "Denegado"}
                </span>
              </li>
            ))}
          </ul>
        )}
        {audit.total > audit.items.length ? (
          <p className="hint">
            Mostrando {audit.items.length} de {audit.total} registros.
          </p>
        ) : null}
      </section>
    </div>
  );
}
