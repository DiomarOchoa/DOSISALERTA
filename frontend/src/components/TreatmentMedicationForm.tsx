// Bloque de un medicamento dentro de un tratamiento
// (Fase 8, Entrega 3): seleccion, dosis, unidad, indicaciones y
// horarios. Se usa igual en el formulario de creacion (una copia
// por medicamento) y al anadir un medicamento a un tratamiento
// existente (una copia).
//
// Validacion igual a la del backend (TreatmentMedicationCreate y
// ScheduleCreate), mas la regla de la web (decision 1): al menos
// un horario valido por medicamento, aunque la API lo permita
// opcional al anadir. La dosis es mayor que 0, maximo 10 digitos
// y 3 decimales; la unidad, de 1 a 30 caracteres.

import type { Medication } from "../services/medications";
import type { ScheduleCreateInput, TreatmentMedicationCreateInput } from "../services/treatments";
import { UNIT_OPTIONS } from "./medicationOptions";
import ScheduleForm, {
  emptySchedule,
  validateSchedule,
  type ScheduleErrors,
} from "./ScheduleForm";

export function emptyTreatmentMedication(
  defaultStartDate: string,
): TreatmentMedicationCreateInput {
  return {
    medication_id: 0,
    dose_amount: 0,
    dose_unit: "",
    instructions: null,
    schedules: [emptySchedule(defaultStartDate)],
  };
}

export type MedicationBlockErrors = Record<string, string>;

export function validateTreatmentMedication(
  med: TreatmentMedicationCreateInput,
  prefix = "",
): MedicationBlockErrors {
  const errors: MedicationBlockErrors = {};
  const at = (field: string) => (prefix ? `${prefix}.${field}` : field);

  if (!med.medication_id || med.medication_id <= 0) {
    errors[at("medication_id")] = "Elige un medicamento.";
  }
  if (Number.isNaN(med.dose_amount) || med.dose_amount <= 0) {
    errors[at("dose_amount")] =
      "La dosis debe ser un número mayor que 0.";
  } else {
    const text = String(med.dose_amount);
    const decimals = text.includes(".")
      ? text.split(".")[1].length
      : 0;
    const digits = text.replace(".", "").replace("-", "").length;
    if (decimals > 3 || digits > 10) {
      errors[at("dose_amount")] =
        "La dosis admite como máximo 10 dígitos y 3 decimales.";
    }
  }
  if (!med.dose_unit.trim()) {
    errors[at("dose_unit")] = "La unidad es obligatoria.";
  } else if (med.dose_unit.trim().length > 30) {
    errors[at("dose_unit")] =
      "La unidad admite como máximo 30 caracteres.";
  }
  const schedules = med.schedules ?? [];
  if (schedules.length === 0) {
    errors[at("schedules")] =
      "Añade al menos un horario: sin horario, el medicamento no tiene tomas programadas.";
  } else {
    for (const [index, schedule] of schedules.entries()) {
      const scheduleErrors: ScheduleErrors = validateSchedule(
        schedule,
        `${at("schedules")}.${index}`,
      );
      Object.assign(errors, scheduleErrors);
    }
  }
  return errors;
}

interface TreatmentMedicationFormProps {
  value: TreatmentMedicationCreateInput;
  onChange: (next: TreatmentMedicationCreateInput) => void;
  medications: Medication[];
  onRemove?: () => void;
  removable?: boolean;
  errors?: MedicationBlockErrors;
  errorPrefix?: string;
  disabled?: boolean;
  defaultStartDate: string;
}

export default function TreatmentMedicationForm({
  value,
  onChange,
  medications,
  onRemove,
  removable = false,
  errors = {},
  errorPrefix = "",
  disabled = false,
  defaultStartDate,
}: TreatmentMedicationFormProps) {
  const err = (field: string) =>
    errors[errorPrefix ? `${errorPrefix}.${field}` : field];

  function set(patch: Partial<TreatmentMedicationCreateInput>) {
    onChange({ ...value, ...patch });
  }

  function setSchedule(index: number, next: ScheduleCreateInput) {
    const schedules = (value.schedules ?? []).map((item, i) =>
      i === index ? next : item,
    );
    set({ schedules });
  }

  function addSchedule() {
    set({
      schedules: [
        ...(value.schedules ?? []),
        emptySchedule(defaultStartDate),
      ],
    });
  }

  function removeSchedule(index: number) {
    const schedules = (value.schedules ?? []).filter(
      (_, i) => i !== index,
    );
    set({ schedules });
  }

  return (
    <div className="med-block">
      <div className="field">
        <label htmlFor={`med-${errorPrefix || "nuevo"}`}>
          Medicamento
        </label>
        <select
          id={`med-${errorPrefix || "nuevo"}`}
          value={value.medication_id || ""}
          disabled={disabled}
          onChange={(event) => {
            const medicationId = Number(event.target.value);
            const picked = medications.find(
              (med) => med.id === medicationId,
            );
            // Si la unidad de la dosis está vacía, se hereda la del
            // medicamento elegido; si ya tiene valor, no se toca.
            set({
              medication_id: medicationId,
              dose_unit:
                !value.dose_unit.trim() && picked?.unit
                  ? picked.unit
                  : value.dose_unit,
            });
          }}
        >
          <option value="" disabled>
            Elige un medicamento activo
          </option>
          {medications.map((med) => (
            <option key={med.id} value={med.id}>
              {med.name}
              {[med.presentation, med.concentration]
                .filter(Boolean)
                .join(" · ")
                ? ` — ${[med.presentation, med.concentration].filter(Boolean).join(" · ")}`
                : ""}
            </option>
          ))}
        </select>
        {err("medication_id") ? (
          <p className="field-error">{err("medication_id")}</p>
        ) : null}
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor={`dose-${errorPrefix || "nuevo"}`}>Dosis</label>
          <input
            id={`dose-${errorPrefix || "nuevo"}`}
            type="number"
            min={0}
            step="0.001"
            value={value.dose_amount || ""}
            disabled={disabled}
            onChange={(event) =>
              set({
                dose_amount:
                  event.target.value === ""
                    ? 0
                    : Number(event.target.value),
              })
            }
          />
          {err("dose_amount") ? (
            <p className="field-error">{err("dose_amount")}</p>
          ) : null}
        </div>
        <div className="field">
          <label htmlFor={`unit-${errorPrefix || "nuevo"}`}>Unidad</label>
          <input
            id={`unit-${errorPrefix || "nuevo"}`}
            type="text"
            maxLength={30}
            list={`unit-options-${errorPrefix || "nuevo"}`}
            placeholder="Elige o escribe la unidad"
            value={value.dose_unit}
            disabled={disabled}
            onChange={(event) => set({ dose_unit: event.target.value })}
          />
          <datalist id={`unit-options-${errorPrefix || "nuevo"}`}>
            {UNIT_OPTIONS.map((option) => (
              <option key={option} value={option} />
            ))}
          </datalist>
          {err("dose_unit") ? (
            <p className="field-error">{err("dose_unit")}</p>
          ) : null}
        </div>
      </div>

      <div className="field">
        <label htmlFor={`notes-${errorPrefix || "nuevo"}`}>
          Indicaciones (opcional)
        </label>
        <textarea
          id={`notes-${errorPrefix || "nuevo"}`}
          value={value.instructions ?? ""}
          disabled={disabled}
          onChange={(event) =>
            set({ instructions: event.target.value || null })
          }
        />
      </div>

      <div className="field">
        <span className="field-label">Horarios</span>
        {(value.schedules ?? []).map((schedule, index) => (
          <ScheduleForm
            key={index}
            value={schedule}
            onChange={(next) => setSchedule(index, next)}
            onRemove={() => removeSchedule(index)}
            removable={(value.schedules ?? []).length > 1}
            errors={errors}
            errorPrefix={`${errorPrefix ? `${errorPrefix}.` : ""}schedules.${index}`}
            disabled={disabled}
          />
        ))}
        <button
          type="button"
          className="btn-ghost"
          disabled={disabled}
          onClick={addSchedule}
        >
          Añadir otro horario
        </button>
        {err("schedules") ? (
          <p className="field-error">{err("schedules")}</p>
        ) : null}
      </div>

      {removable && onRemove ? (
        <button
          type="button"
          className="btn-danger"
          disabled={disabled}
          onClick={onRemove}
        >
          Quitar este medicamento
        </button>
      ) : null}
    </div>
  );
}
