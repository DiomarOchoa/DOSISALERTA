// Detalle de un tratamiento (Entrega 3).
// - GET /treatments/{id}: 404 si no existe, 403 si es de otro
//   usuario; en ambos casos se muestra el estado, nunca los datos
//   de otra persona.
// - Acciones segun la maquina de estados: ACTIVO -> Pausar /
//   Cancelar / Completar; PAUSADO -> Reanudar / Cancelar;
//   COMPLETADO y CANCELADO son terminales y no ofrecen acciones.
//   Cancelar y Completar son irreversibles y piden confirmacion.
// - Edicion en linea de titulo, notas y fecha de fin (solo se
//   envian los campos que cambiaron; PATCH exige al menos uno).
// - Medicamentos: anadir (con al menos un horario, decision 1),
//   quitar (confirmacion), editar dosis/unidad/indicaciones.
// - Cambiar horarios (decision 2): la API no tiene edicion directa
//   de horarios. El procedimiento es quitar el vinculo (se cancelan
//   sus recordatorios futuros) y volver a anadir el medicamento con
//   los horarios corregidos, con advertencia y confirmacion
//   explicita antes de quitar nada. Si no se completa el formulario,
//   el medicamento queda fuera del tratamiento.
// - Proximas tomas: solo `upcoming_reminders` del backend; nunca
//   se calcula una toma. Inicio futuro o ventana de 72 horas
//   agotada se explican con honestidad.

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "../services/api";
import { listMedications, type Medication } from "../services/medications";
import {
  addTreatmentMedication,
  cancelTreatment,
  completeTreatment,
  getTreatment,
  pauseTreatment,
  removeTreatmentMedication,
  resumeTreatment,
  updateTreatment,
  updateTreatmentMedication,
  type Schedule,
  type ScheduleCreateInput,
  type Treatment,
  type TreatmentMedication,
  type TreatmentMedicationCreateInput,
} from "../services/treatments";
import ApiErrorCard from "../components/ApiErrorCard";
import TreatmentMedicationForm, {
  emptyTreatmentMedication,
  validateTreatmentMedication,
  type MedicationBlockErrors,
} from "../components/TreatmentMedicationForm";
import UpcomingReminders from "../components/UpcomingReminders";
import { useAuth } from "../context/AuthContext";
import { formatDate, formatDateOnly } from "../utils/user";
import { STATUS_BADGE, STATUS_LABEL } from "./TreatmentsPage";

const DAY_NAMES = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"];

function describeSchedule(schedule: Schedule): string {
  const times = schedule.times.join(", ");
  const dates =
    `${formatDateOnly(schedule.start_date)}` +
    (schedule.end_date ? ` – ${formatDateOnly(schedule.end_date)}` : "");
  if (schedule.frequency === "DIARIO") {
    return `Todos los días · ${times} · ${dates}`;
  }
  if (schedule.frequency === "DIAS_SEMANA") {
    const days = (schedule.days_of_week ?? [])
      .map((day) => DAY_NAMES[day])
      .join(", ");
    return `${days} · ${times} · ${dates}`;
  }
  return `Cada ${schedule.interval_days ?? 1} días · ${times} · ${dates}`;
}

function todayLocal(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

type Action = "pause" | "resume" | "cancel" | "complete";

export default function TreatmentDetailPage() {
  const { id } = useParams<{ id: string }>();
  const trtId = Number(id);
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";

  const [treatment, setTreatment] = useState<Treatment | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editEndDate, setEditEndDate] = useState("");
  const [editError, setEditError] = useState<string | null>(null);
  const [savingEdit, setSavingEdit] = useState(false);

  const [confirmAction, setConfirmAction] = useState<Action | null>(null);
  const [acting, setActing] = useState(false);

  const [medications, setMedications] = useState<Medication[]>([]);
  const [addOpen, setAddOpen] = useState(false);
  const [addBlock, setAddBlock] = useState<TreatmentMedicationCreateInput>(
    emptyTreatmentMedication(todayLocal()),
  );
  const [addErrors, setAddErrors] = useState<MedicationBlockErrors>({});
  const [addServerError, setAddServerError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [addNote, setAddNote] = useState<string | null>(null);

  const [confirmRemoveId, setConfirmRemoveId] = useState<number | null>(null);
  const [removing, setRemoving] = useState(false);

  const [editingDoseId, setEditingDoseId] = useState<number | null>(null);
  const [doseAmount, setDoseAmount] = useState("");
  const [doseUnit, setDoseUnit] = useState("");
  const [doseInstructions, setDoseInstructions] = useState("");
  const [doseError, setDoseError] = useState<string | null>(null);
  const [savingDose, setSavingDose] = useState(false);

  const [confirmChangeId, setConfirmChangeId] = useState<number | null>(null);
  const [changingSchedule, setChangingSchedule] = useState(false);

  async function load() {
    if (!Number.isInteger(trtId)) {
      setError(new ApiError(404, "Este tratamiento no existe."));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getTreatment(trtId);
      setTreatment(data);
      setMedications(await listMedications(true));
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo cargar el tratamiento."),
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // Solo al entrar a la pagina (o cambiar de id).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trtId]);

  async function runAction(action: Action) {
    if (!treatment) {
      return;
    }
    setActing(true);
    setSuccess(null);
    try {
      if (action === "pause") {
        await pauseTreatment(treatment.id);
        setSuccess("Tratamiento pausado. Sus recordatorios futuros quedan cancelados.");
      } else if (action === "resume") {
        await resumeTreatment(treatment.id);
        setSuccess("Tratamiento reanudado.");
      } else if (action === "cancel") {
        await cancelTreatment(treatment.id);
        setSuccess("Tratamiento cancelado. Esta operación no se puede deshacer.");
      } else {
        await completeTreatment(treatment.id);
        setSuccess("Tratamiento completado. Esta operación no se puede deshacer.");
      }
      // Recargar desde el servidor: la respuesta de la accion no
      // siempre trae las secciones anidadas actualizadas (por
      // ejemplo, las proximas tomas tras reanudar).
      const fresh = await getTreatment(treatment.id);
      setTreatment(fresh);
      setConfirmAction(null);
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo ejecutar la acción."),
      );
    } finally {
      setActing(false);
    }
  }

  function startEditing() {
    if (!treatment) {
      return;
    }
    setEditTitle(treatment.title);
    setEditNotes(treatment.notes ?? "");
    setEditEndDate(treatment.end_date ?? "");
    setEditError(null);
    setEditing(true);
  }

  async function handleSaveEdit(event: React.FormEvent) {
    event.preventDefault();
    if (!treatment) {
      return;
    }
    const patch: {
      title?: string | null;
      notes?: string | null;
      end_date?: string | null;
    } = {};
    if (editTitle.trim() !== treatment.title) {
      patch.title = editTitle.trim();
    }
    if ((editNotes.trim() || null) !== treatment.notes) {
      patch.notes = editNotes.trim() || null;
    }
    if ((editEndDate || null) !== treatment.end_date) {
      patch.end_date = editEndDate || null;
    }
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      return;
    }
    if (patch.title && patch.title.length > 150) {
      setEditError("El título admite como máximo 150 caracteres.");
      return;
    }
    if (
      patch.end_date &&
      treatment.start_date &&
      patch.end_date < treatment.start_date
    ) {
      setEditError(
        "La fecha de fin no puede ser anterior a la de inicio.",
      );
      return;
    }
    setSavingEdit(true);
    setSuccess(null);
    try {
      const updated = await updateTreatment(treatment.id, patch);
      setTreatment(updated);
      setEditing(false);
      setSuccess("Cambios guardados.");
    } catch (caught) {
      setEditError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudieron guardar los cambios.",
      );
    } finally {
      setSavingEdit(false);
    }
  }

  async function handleAddMedication(event: React.FormEvent) {
    event.preventDefault();
    if (!treatment) {
      return;
    }
    const found = validateTreatmentMedication(addBlock, "add");
    setAddErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    setAdding(true);
    setAddServerError(null);
    setSuccess(null);
    try {
      await addTreatmentMedication(treatment.id, {
        medication_id: addBlock.medication_id,
        dose_amount: addBlock.dose_amount,
        dose_unit: addBlock.dose_unit.trim(),
        instructions: addBlock.instructions?.trim() || null,
        schedules: (addBlock.schedules ?? []).map((schedule) => ({
          frequency: schedule.frequency,
          days_of_week:
            schedule.frequency === "DIAS_SEMANA"
              ? schedule.days_of_week
              : null,
          interval_days:
            schedule.frequency === "INTERVALO_DIAS"
              ? schedule.interval_days
              : null,
          times: schedule.times.filter((time) => time.trim() !== ""),
          start_date: schedule.start_date,
          end_date: schedule.end_date || null,
        })),
      });
      setAddOpen(false);
      setAddNote(null);
      setAddBlock(emptyTreatmentMedication(treatment.start_date));
      setSuccess("Medicamento añadido al tratamiento.");
      await load();
    } catch (caught) {
      setAddServerError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudo añadir el medicamento.",
      );
    } finally {
      setAdding(false);
    }
  }

  async function handleRemoveLink(link: TreatmentMedication) {
    if (!treatment) {
      return;
    }
    setRemoving(true);
    setSuccess(null);
    try {
      await removeTreatmentMedication(treatment.id, link.id);
      setConfirmRemoveId(null);
      setSuccess(
        `«${link.medication.name}» se quitó del tratamiento. Sus recordatorios futuros quedan cancelados.`,
      );
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo quitar el medicamento."),
      );
    } finally {
      setRemoving(false);
    }
  }

  function startEditingDose(link: TreatmentMedication) {
    setEditingDoseId(link.id);
    setDoseAmount(String(link.dose_amount));
    setDoseUnit(link.dose_unit);
    setDoseInstructions(link.instructions ?? "");
    setDoseError(null);
  }

  async function handleSaveDose(event: React.FormEvent, link: TreatmentMedication) {
    event.preventDefault();
    if (!treatment) {
      return;
    }
    const patch: {
      dose_amount?: number;
      dose_unit?: string;
      instructions?: string | null;
    } = {};
    const amount = Number(doseAmount);
    if (doseAmount !== "" && amount !== link.dose_amount) {
      patch.dose_amount = amount;
    }
    if (doseUnit.trim() !== link.dose_unit) {
      patch.dose_unit = doseUnit.trim();
    }
    if ((doseInstructions.trim() || null) !== link.instructions) {
      patch.instructions = doseInstructions.trim() || null;
    }
    if (Object.keys(patch).length === 0) {
      setEditingDoseId(null);
      return;
    }
    if (
      patch.dose_amount !== undefined &&
      (Number.isNaN(patch.dose_amount) || patch.dose_amount <= 0)
    ) {
      setDoseError("La dosis debe ser un número mayor que 0.");
      return;
    }
    if (patch.dose_unit !== undefined && patch.dose_unit.length > 30) {
      setDoseError("La unidad admite como máximo 30 caracteres.");
      return;
    }
    setSavingDose(true);
    setSuccess(null);
    try {
      await updateTreatmentMedication(treatment.id, link.id, patch);
      setEditingDoseId(null);
      setSuccess("Dosis actualizada.");
      await load();
    } catch (caught) {
      setDoseError(
        caught instanceof ApiError
          ? caught.message
          : "No se pudo actualizar la dosis.",
      );
    } finally {
      setSavingDose(false);
    }
  }

  // Cambiar horarios: quitar el vinculo y volver a anadirlo con los
  // horarios corregidos (decision 2). Solo se quita tras la
  // confirmacion explicita; el formulario se prellena con los datos
  // anteriores para corregir solo los horarios.
  async function handleChangeSchedules(link: TreatmentMedication) {
    if (!treatment) {
      return;
    }
    setChangingSchedule(true);
    setSuccess(null);
    try {
      await removeTreatmentMedication(treatment.id, link.id);
      const schedules: ScheduleCreateInput[] = (
        link.schedules ?? []
      ).map((schedule) => ({
        frequency: schedule.frequency,
        days_of_week: schedule.days_of_week,
        interval_days: schedule.interval_days,
        times: schedule.times,
        start_date: schedule.start_date,
        end_date: schedule.end_date,
      }));
      setAddBlock({
        medication_id: link.medication_id,
        dose_amount: link.dose_amount,
        dose_unit: link.dose_unit,
        instructions: link.instructions,
        schedules:
          schedules.length > 0
            ? schedules
            : [emptyTreatmentMedication(treatment.start_date).schedules![0]],
      });
      setAddErrors({});
      setAddServerError(null);
      setConfirmChangeId(null);
      setAddOpen(true);
      setAddNote(
        `«${link.medication.name}» quedó fuera del tratamiento. Corrige los horarios y pulsa «Añadir medicamento» para volver a vincularlo; si no lo haces, quedará fuera.`,
      );
      await load();
    } catch (caught) {
      setError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo quitar el vínculo."),
      );
    } finally {
      setChangingSchedule(false);
    }
  }

  if (loading) {
    return (
      <section className="card">
        <h2>Tratamiento</h2>
        <p>Cargando el tratamiento…</p>
      </section>
    );
  }

  if (error) {
    return (
      <ApiErrorCard
        error={error}
        onRetry={load}
        resource="tratamiento"
        backTo="/tratamientos"
        backLabel="Volver a Tratamientos"
      />
    );
  }

  if (!treatment) {
    return (
      <ApiErrorCard
        error={new ApiError(404, "Este tratamiento no existe.")}
        resource="tratamiento"
        backTo="/tratamientos"
        backLabel="Volver a Tratamientos"
      />
    );
  }

  const activeLinks = (treatment.medications ?? []).filter(
    (link) => link.is_active,
  );
  const inactiveCount = (treatment.medications ?? []).length - activeLinks.length;
  const linkedMedIds = new Set(activeLinks.map((link) => link.medication_id));
  const availableMeds = medications.filter(
    (med) => !linkedMedIds.has(med.id),
  );
  const isFutureStart =
    treatment.start_date > todayLocal() &&
    (treatment.upcoming_reminders ?? []).length === 0;
  const canAct = treatment.status === "ACTIVO" || treatment.status === "PAUSADO";

  return (
    <>
      <div className="page-head">
        <h2>{treatment.title}</h2>
        <span className={STATUS_BADGE[treatment.status]}>
          {STATUS_LABEL[treatment.status]}
        </span>
      </div>

      {success ? <p className="success-box">{success}</p> : null}

      {isFutureStart ? (
        <div className="warn-box">
          <p>
            Este tratamiento empieza el{" "}
            {formatDateOnly(treatment.start_date)}: todavía no genera
            recordatorios.
          </p>
        </div>
      ) : null}

      {editing ? (
        <section className="card">
          <h2>Editar tratamiento</h2>
          <form className="form" onSubmit={handleSaveEdit} noValidate>
            <div className="field">
              <label htmlFor="trt-edit-title">Título</label>
              <input
                id="trt-edit-title"
                type="text"
                maxLength={150}
                value={editTitle}
                disabled={savingEdit}
                onChange={(event) => setEditTitle(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="trt-edit-notes">Notas</label>
              <textarea
                id="trt-edit-notes"
                value={editNotes}
                disabled={savingEdit}
                onChange={(event) => setEditNotes(event.target.value)}
              />
            </div>
            <div className="field">
              <label htmlFor="trt-edit-end">
                Fecha de fin (opcional)
              </label>
              <input
                id="trt-edit-end"
                type="date"
                value={editEndDate}
                disabled={savingEdit}
                onChange={(event) => setEditEndDate(event.target.value)}
              />
            </div>
            {editError ? <p className="field-error">{editError}</p> : null}
            <div className="confirm-actions">
              <button type="submit" disabled={savingEdit}>
                {savingEdit ? "Guardando…" : "Guardar cambios"}
              </button>
              <button
                type="button"
                className="btn-ghost"
                disabled={savingEdit}
                onClick={() => setEditing(false)}
              >
                Cancelar
              </button>
            </div>
          </form>
        </section>
      ) : (
        <section className="card">
          <div className="profile-row">
            <span className="row-label">Inicio</span>
            <span className="row-value">
              {formatDateOnly(treatment.start_date)}
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label">Fin</span>
            <span className="row-value">
              {treatment.end_date
                ? formatDateOnly(treatment.end_date)
                : "Sin fecha de fin"}
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label">Notas</span>
            <span className="row-value">{treatment.notes ?? "—"}</span>
          </div>
          <div className="profile-row">
            <span className="row-label">Creado</span>
            <span className="row-value">
              {formatDate(treatment.created_at)}
            </span>
          </div>
          <div className="profile-row">
            <span className="row-label">Actualizado</span>
            <span className="row-value">
              {formatDate(treatment.updated_at)}
            </span>
          </div>

          <div className="confirm-actions" style={{ marginTop: "1rem" }}>
            <button type="button" onClick={startEditing}>
              Editar
            </button>
            {treatment.status === "ACTIVO" ? (
              <button
                type="button"
                className="btn-ghost"
                disabled={acting}
                onClick={() => runAction("pause")}
              >
                {acting ? "Pausando…" : "Pausar"}
              </button>
            ) : null}
            {treatment.status === "PAUSADO" ? (
              <button
                type="button"
                disabled={acting}
                onClick={() => runAction("resume")}
              >
                {acting ? "Reanudando…" : "Reanudar"}
              </button>
            ) : null}
            {canAct ? (
              <>
                <button
                  type="button"
                  className="btn-danger"
                  disabled={acting}
                  onClick={() => setConfirmAction("cancel")}
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  className="btn-danger"
                  disabled={acting}
                  onClick={() => setConfirmAction("complete")}
                >
                  Completar
                </button>
              </>
            ) : null}
            <Link className="btn-ghost" to="/tratamientos">
              Volver
            </Link>
          </div>

          {treatment.status === "COMPLETADO" ||
          treatment.status === "CANCELADO" ? (
            <p className="hint" style={{ marginTop: "1rem" }}>
              Estado terminal: este tratamiento ya no admite cambios de
              estado.
            </p>
          ) : null}

          {confirmAction === "cancel" || confirmAction === "complete" ? (
            <div className="confirm-box">
              <p>
                {confirmAction === "cancel"
                  ? "¿Cancelar este tratamiento? Sus recordatorios futuros se cancelan y esta operación no se puede deshacer."
                  : "¿Completar este tratamiento? Sus recordatorios futuros se cancelan y esta operación no se puede deshacer."}
              </p>
              <div className="confirm-actions">
                <button
                  type="button"
                  className="btn-danger"
                  disabled={acting}
                  onClick={() => runAction(confirmAction)}
                >
                  {acting
                    ? "Ejecutando…"
                    : confirmAction === "cancel"
                      ? "Sí, cancelar"
                      : "Sí, completar"}
                </button>
                <button
                  type="button"
                  className="btn-ghost"
                  disabled={acting}
                  onClick={() => setConfirmAction(null)}
                >
                  Volver
                </button>
              </div>
            </div>
          ) : null}
        </section>
      )}

      <section className="card">
        <h2>Medicamentos</h2>
        {activeLinks.length === 0 ? (
          <p>
            Este tratamiento no tiene medicamentos vinculados.
          </p>
        ) : (
          <ul className="dose-list">
            {activeLinks.map((link) => (
              <li key={link.id} className="dose-item" data-link-id={link.id}>
                <p className="med-name">{link.medication.name}</p>
                <p className="med-meta">
                  {[link.medication.presentation, link.medication.concentration]
                    .filter(Boolean)
                    .join(" · ") || "Sin detalles"}
                </p>
                <p className="med-meta">
                  Dosis: {link.dose_amount} {link.dose_unit}
                  {link.instructions ? ` · ${link.instructions}` : ""}
                </p>
                {(link.schedules ?? []).length > 0 ? (
                  <ul className="sched-list">
                    {(link.schedules ?? []).map((schedule) => (
                      <li key={schedule.id} className="sched-chip">
                        {describeSchedule(schedule)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">
                    Sin horarios: este medicamento no tiene tomas
                    programadas.
                  </p>
                )}

                {editingDoseId === link.id ? (
                  <form
                    className="form"
                    onSubmit={(event) => handleSaveDose(event, link)}
                    noValidate
                  >
                    <div className="field-row">
                      <div className="field">
                        <label htmlFor={`dose-amount-${link.id}`}>
                          Dosis
                        </label>
                        <input
                          id={`dose-amount-${link.id}`}
                          type="number"
                          min={0}
                          step="0.001"
                          value={doseAmount}
                          disabled={savingDose}
                          onChange={(event) =>
                            setDoseAmount(event.target.value)
                          }
                        />
                      </div>
                      <div className="field">
                        <label htmlFor={`dose-unit-${link.id}`}>
                          Unidad
                        </label>
                        <input
                          id={`dose-unit-${link.id}`}
                          type="text"
                          maxLength={30}
                          value={doseUnit}
                          disabled={savingDose}
                          onChange={(event) =>
                            setDoseUnit(event.target.value)
                          }
                        />
                      </div>
                    </div>
                    <div className="field">
                      <label htmlFor={`dose-notes-${link.id}`}>
                        Indicaciones
                      </label>
                      <textarea
                        id={`dose-notes-${link.id}`}
                        value={doseInstructions}
                        disabled={savingDose}
                        onChange={(event) =>
                          setDoseInstructions(event.target.value)
                        }
                      />
                    </div>
                    {doseError ? (
                      <p className="field-error">{doseError}</p>
                    ) : null}
                    <div className="confirm-actions">
                      <button type="submit" disabled={savingDose}>
                        {savingDose ? "Guardando…" : "Guardar dosis"}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={savingDose}
                        onClick={() => setEditingDoseId(null)}
                      >
                        Cancelar
                      </button>
                    </div>
                  </form>
                ) : (
                  <div className="confirm-actions">
                    {canAct ? (
                      <>
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => startEditingDose(link)}
                        >
                          Editar dosis
                        </button>
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => setConfirmChangeId(link.id)}
                        >
                          Cambiar horarios
                        </button>
                        <button
                          type="button"
                          className="btn-danger"
                          onClick={() => setConfirmRemoveId(link.id)}
                        >
                          Quitar
                        </button>
                      </>
                    ) : null}
                  </div>
                )}

                {confirmRemoveId === link.id ? (
                  <div className="confirm-box">
                    <p>
                      ¿Quitar «{link.medication.name}» del tratamiento?
                      Sus recordatorios futuros se cancelan.
                    </p>
                    <div className="confirm-actions">
                      <button
                        type="button"
                        className="btn-danger"
                        disabled={removing}
                        onClick={() => handleRemoveLink(link)}
                      >
                        {removing ? "Quitando…" : "Sí, quitar"}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={removing}
                        onClick={() => setConfirmRemoveId(null)}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                ) : null}

                {confirmChangeId === link.id ? (
                  <div className="warn-box">
                    <p>
                      La aplicación no permite editar los horarios
                      directamente: no existe esa operación en el
                      backend. El procedimiento es quitar «
                      {link.medication.name}» del tratamiento (se
                      cancelan sus recordatorios futuros) y volver a
                      añadirlo con los horarios corregidos.
                    </p>
                    <p>
                      Si no completas el formulario después, el
                      medicamento quedará fuera del tratamiento.
                    </p>
                    <div className="confirm-actions">
                      <button
                        type="button"
                        className="btn-danger"
                        disabled={changingSchedule}
                        onClick={() => handleChangeSchedules(link)}
                      >
                        {changingSchedule
                          ? "Quitando…"
                          : "Sí, quitar y volver a añadir"}
                      </button>
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={changingSchedule}
                        onClick={() => setConfirmChangeId(null)}
                      >
                        Cancelar
                      </button>
                    </div>
                  </div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
        {inactiveCount > 0 ? (
          <p className="hint">
            {inactiveCount} vínculo{inactiveCount === 1 ? "" : "s"}{" "}
            anterior{inactiveCount === 1 ? "" : "es"} (medicamentos
            quitados).
          </p>
        ) : null}

        {canAct ? (
          addOpen ? (
            <form
              className="form"
              onSubmit={handleAddMedication}
              noValidate
            >
              <h2>Añadir medicamento</h2>
              {addNote ? <p className="warn-box">{addNote}</p> : null}
              {availableMeds.length === 0 ? (
                <p>
                  No quedan medicamentos activos por vincular a este
                  tratamiento.
                </p>
              ) : (
                <>
                  <TreatmentMedicationForm
                    value={addBlock}
                    onChange={setAddBlock}
                    medications={availableMeds}
                    errors={addErrors}
                    errorPrefix="add"
                    disabled={adding}
                    defaultStartDate={treatment.start_date}
                  />
                  {addServerError ? (
                    <p className="field-error">{addServerError}</p>
                  ) : null}
                  <div className="confirm-actions">
                    <button type="submit" disabled={adding}>
                      {adding ? "Añadiendo…" : "Añadir medicamento"}
                    </button>
                    <button
                      type="button"
                      className="btn-ghost"
                      disabled={adding}
                      onClick={() => {
                        setAddOpen(false);
                        setAddNote(null);
                        setAddServerError(null);
                      }}
                    >
                      Cancelar
                    </button>
                  </div>
                </>
              )}
            </form>
          ) : (
            <button
              type="button"
              className="btn-primary"
              onClick={() => {
                setAddBlock(
                  emptyTreatmentMedication(treatment.start_date),
                );
                setAddErrors({});
                setAddServerError(null);
                setAddNote(null);
                setAddOpen(true);
              }}
            >
              Añadir medicamento
            </button>
          )
        ) : null}
      </section>

      <section className="card">
        <h2>Próximas tomas</h2>
        <UpcomingReminders
          reminders={treatment.upcoming_reminders}
          timezone={timezone}
        />
      </section>

      <Link className="btn-ghost" to="/tratamientos">
        Volver a Tratamientos
      </Link>
    </>
  );
}
