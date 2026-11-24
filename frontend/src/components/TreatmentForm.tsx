// Formulario de creacion de un tratamiento (Fase 8, Entrega 3).
// - Titulo, notas, fecha de inicio y fecha de fin opcional.
// - Lista dinamica de medicamentos (decision 4): cada uno con
//   dosis, unidad, indicaciones y al menos un horario.
// - Valida todas las reglas del backend antes de enviar
//   (TreatmentCreate, TreatmentMedicationCreate y ScheduleCreate).
//   Si el servidor rechaza igualmente, su mensaje se muestra tal
//   cual con ApiErrorCard, sin reintentar el POST (podria duplicar).

import { useState } from "react";
import { ApiError } from "../services/api";
import type { Medication } from "../services/medications";
import {
  createTreatment,
  type ScheduleCreateInput,
  type Treatment,
  type TreatmentCreateInput,
  type TreatmentMedicationCreateInput,
} from "../services/treatments";
import ApiErrorCard from "./ApiErrorCard";
import TreatmentMedicationForm, {
  emptyTreatmentMedication,
  validateTreatmentMedication,
  type MedicationBlockErrors,
} from "./TreatmentMedicationForm";

function todayLocal(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// Resumen en palabras simples de lo que se va a crear, para que
// el usuario lo lea y lo confirme antes de guardar. Solo se
// muestran los bloques con medicamento, dosis y unidad completos.
const DAY_NAMES = [
  "lunes",
  "martes",
  "miércoles",
  "jueves",
  "viernes",
  "sábado",
  "domingo",
];

function describeSchedule(schedule: ScheduleCreateInput): string {
  const times = schedule.times.filter((time) => time.trim() !== "");
  if (times.length === 0) {
    return "";
  }
  const hours = times.join(" y ");
  if (schedule.frequency === "DIAS_SEMANA") {
    const days = (schedule.days_of_week ?? [])
      .map((day) => DAY_NAMES[day])
      .join(", ");
    return `${days} a las ${hours}`;
  }
  if (schedule.frequency === "INTERVALO_DIAS") {
    return `cada ${schedule.interval_days ?? 1} días a las ${hours}`;
  }
  return `todos los días a las ${hours}`;
}

function buildSummary(
  blocks: TreatmentMedicationCreateInput[],
  medications: Medication[],
): string[] {
  return blocks
    .filter(
      (block) =>
        block.medication_id > 0 &&
        block.dose_amount > 0 &&
        block.dose_unit.trim(),
    )
    .map((block) => {
      const med = medications.find((item) => item.id === block.medication_id);
      const name = med?.name ?? "Medicamento";
      const schedules = (block.schedules ?? [])
        .map(describeSchedule)
        .filter(Boolean)
        .join("; ");
      return schedules
        ? `${name}: ${block.dose_amount} ${block.dose_unit.trim()}, ${schedules}.`
        : `${name}: ${block.dose_amount} ${block.dose_unit.trim()}.`;
    });
}

// Primer bloque del formulario. Si se llega desde el detalle de
// un medicamento, ese medicamento ya viene elegido y su unidad
// como unidad de la dosis.
function initialBlock(
  startDate: string,
  medicationId: number | undefined,
  medications: Medication[],
): TreatmentMedicationCreateInput {
  const block = emptyTreatmentMedication(startDate);
  if (!medicationId) {
    return block;
  }
  const picked = medications.find((med) => med.id === medicationId);
  if (!picked) {
    return block;
  }
  return {
    ...block,
    medication_id: picked.id,
    dose_unit: picked.unit ?? "",
  };
}

interface TreatmentFormProps {
  medications: Medication[];
  preselectedMedicationId?: number;
  onSaved: (treatment: Treatment) => void;
  onCancel?: () => void;
}

export default function TreatmentForm({
  medications,
  preselectedMedicationId,
  onSaved,
  onCancel,
}: TreatmentFormProps) {
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [startDate, setStartDate] = useState(todayLocal());
  const [endDate, setEndDate] = useState("");
  const [blocks, setBlocks] = useState<TreatmentMedicationCreateInput[]>(
    () => [
      initialBlock(todayLocal(), preselectedMedicationId, medications),
    ],
  );
  const [errors, setErrors] = useState<MedicationBlockErrors>({});
  const [serverError, setServerError] = useState<ApiError | null>(null);
  const [saving, setSaving] = useState(false);

  function setBlock(index: number, next: TreatmentMedicationCreateInput) {
    setBlocks((current) =>
      current.map((item, i) => (i === index ? next : item)),
    );
  }

  function addBlock() {
    setBlocks((current) => [
      ...current,
      emptyTreatmentMedication(startDate),
    ]);
  }

  function removeBlock(index: number) {
    setBlocks((current) => current.filter((_, i) => i !== index));
  }

  function handleStartDateChange(next: string) {
    const previous = startDate;
    setStartDate(next);
    // Los horarios que todavia tenian la fecha anterior la siguen.
    setBlocks((current) =>
      current.map((block) => ({
        ...block,
        schedules: (block.schedules ?? []).map((schedule) =>
          schedule.start_date === previous
            ? { ...schedule, start_date: next }
            : schedule,
        ),
      })),
    );
  }

  function validate(): MedicationBlockErrors {
    const found: MedicationBlockErrors = {};
    if (!title.trim()) {
      found.title = "El título es obligatorio.";
    } else if (title.trim().length > 150) {
      found.title = "El título admite como máximo 150 caracteres.";
    }
    if (!startDate) {
      found.start_date = "La fecha de inicio es obligatoria.";
    }
    if (endDate && startDate && endDate < startDate) {
      found.end_date =
        "La fecha de fin no puede ser anterior a la de inicio.";
    }
    if (blocks.length === 0) {
      found.medications = "Añade al menos un medicamento.";
    }
    blocks.forEach((block, index) => {
      Object.assign(
        found,
        validateTreatmentMedication(block, `medications.${index}`),
      );
    });
    return found;
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const found = validate();
    setErrors(found);
    if (Object.keys(found).length > 0) {
      return;
    }
    setSaving(true);
    setServerError(null);
    const payload: TreatmentCreateInput = {
      title: title.trim(),
      notes: notes.trim() || null,
      start_date: startDate,
      end_date: endDate || null,
      medications: blocks.map((block) => ({
        medication_id: block.medication_id,
        dose_amount: block.dose_amount,
        dose_unit: block.dose_unit.trim(),
        instructions: block.instructions?.trim() || null,
        schedules: (block.schedules ?? []).map((schedule) => ({
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
      })),
    };
    try {
      const created = await createTreatment(payload);
      onSaved(created);
    } catch (caught) {
      setServerError(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "No se pudo crear el tratamiento."),
      );
    } finally {
      setSaving(false);
    }
  }

  const summary = buildSummary(blocks, medications);

  return (
    <>
      {serverError ? <ApiErrorCard error={serverError} /> : null}
      <form className="form" onSubmit={handleSubmit} noValidate>
        <div className="field">
          <label htmlFor="trt-title">Título</label>
          <input
            id="trt-title"
            type="text"
            maxLength={150}
            value={title}
            disabled={saving}
            onChange={(event) => setTitle(event.target.value)}
          />
          {errors.title ? (
            <p className="field-error">{errors.title}</p>
          ) : null}
        </div>

        <div className="field">
          <label htmlFor="trt-notes">Notas (opcional)</label>
          <textarea
            id="trt-notes"
            value={notes}
            disabled={saving}
            onChange={(event) => setNotes(event.target.value)}
          />
        </div>

        <div className="field-row">
          <div className="field">
            <label htmlFor="trt-start">Fecha de inicio</label>
            <input
              id="trt-start"
              type="date"
              value={startDate}
              disabled={saving}
              onChange={(event) =>
                handleStartDateChange(event.target.value)
              }
            />
            {errors.start_date ? (
              <p className="field-error">{errors.start_date}</p>
            ) : null}
          </div>
          <div className="field">
            <label htmlFor="trt-end">Fecha de fin (opcional)</label>
            <input
              id="trt-end"
              type="date"
              value={endDate}
              disabled={saving}
              onChange={(event) => setEndDate(event.target.value)}
            />
            {errors.end_date ? (
              <p className="field-error">{errors.end_date}</p>
            ) : null}
          </div>
        </div>

        <div className="field">
          <span className="field-label">Medicamentos</span>
          <p className="hint">
            Cada medicamento necesita su dosis y al menos un horario.
          </p>
          {blocks.map((block, index) => (
            <TreatmentMedicationForm
              key={index}
              value={block}
              onChange={(next) => setBlock(index, next)}
              medications={medications}
              onRemove={() => removeBlock(index)}
              removable={blocks.length > 1}
              errors={errors}
              errorPrefix={`medications.${index}`}
              disabled={saving}
              defaultStartDate={startDate}
            />
          ))}
          <button
            type="button"
            className="btn-ghost"
            disabled={saving}
            onClick={addBlock}
          >
            Añadir otro medicamento
          </button>
          {errors.medications ? (
            <p className="field-error">{errors.medications}</p>
          ) : null}
        </div>

        {summary.length > 0 ? (
          <div className="summary-box">
            <span className="field-label">Resumen</span>
            <ul>
              {summary.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="hint">
            Completa el medicamento, la dosis y al menos un horario y
            aquí verás el resumen en palabras simples.
          </p>
        )}

        <div className="confirm-actions">
          <button type="submit" disabled={saving}>
            {saving ? "Creando…" : "Crear tratamiento"}
          </button>
          {onCancel ? (
            <button
              type="button"
              className="btn-ghost"
              disabled={saving}
              onClick={onCancel}
            >
              Cancelar
            </button>
          ) : null}
        </div>
      </form>
    </>
  );
}
