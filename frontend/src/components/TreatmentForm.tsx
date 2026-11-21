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

interface TreatmentFormProps {
  medications: Medication[];
  onSaved: (treatment: Treatment) => void;
  onCancel?: () => void;
}

export default function TreatmentForm({
  medications,
  onSaved,
  onCancel,
}: TreatmentFormProps) {
  const [title, setTitle] = useState("");
  const [notes, setNotes] = useState("");
  const [startDate, setStartDate] = useState(todayLocal());
  const [endDate, setEndDate] = useState("");
  const [blocks, setBlocks] = useState<TreatmentMedicationCreateInput[]>([
    emptyTreatmentMedication(todayLocal()),
  ]);
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
