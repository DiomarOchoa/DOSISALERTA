// Formulario de un horario de toma (Fase 8, Entrega 3).
// Reglas validadas aqui antes de enviar, iguales a las del
// backend (ScheduleCreate): frecuencia DIARIO | DIAS_SEMANA |
// INTERVALO_DIAS; DIAS_SEMANA exige dias de la semana (0=lunes..6);
// INTERVALO_DIAS exige interval_days >= 1; al menos una hora;
// fecha de inicio obligatoria; fecha de fin >= inicio.
//
// Un horario nuevo sin fecha de inicio hereda la del tratamiento
// (prop `defaultStartDate`), para no pedir la misma fecha dos
// veces. Las horas son HH:MM locales; el backend las guarda como
// horas de pared en la zona horaria del usuario.

import type { ScheduleCreateInput, ScheduleFrequency } from "../services/treatments";

const DAYS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

export type ScheduleErrors = Record<string, string>;

export function emptySchedule(defaultStartDate: string): ScheduleCreateInput {
  return {
    frequency: "DIARIO",
    days_of_week: null,
    interval_days: null,
    times: ["08:00"],
    start_date: defaultStartDate,
    end_date: null,
  };
}

// Valida un horario con las mismas reglas del backend. Devuelve un
// mapa campo -> mensaje; vacio si todo es valido. Las claves usan
// prefijo cuando el horario forma parte de una lista, para que el
// formulario padre pueda mostrar cada error en su sitio.
export function validateSchedule(
  schedule: ScheduleCreateInput,
  prefix = "",
): ScheduleErrors {
  const errors: ScheduleErrors = {};
  const at = (field: string) => (prefix ? `${prefix}.${field}` : field);

  if (schedule.frequency === "DIAS_SEMANA") {
    if (!schedule.days_of_week || schedule.days_of_week.length === 0) {
      errors[at("days_of_week")] =
        "Elige al menos un día de la semana.";
    }
  }
  if (schedule.frequency === "INTERVALO_DIAS") {
    if (
      schedule.interval_days === null ||
      schedule.interval_days === undefined ||
      !Number.isInteger(schedule.interval_days) ||
      schedule.interval_days < 1
    ) {
      errors[at("interval_days")] =
        "El intervalo debe ser un número entero de días (mínimo 1).";
    }
  }
  const times = schedule.times.filter((time) => time.trim() !== "");
  if (times.length === 0) {
    errors[at("times")] = "Añade al menos una hora.";
  }
  if (!schedule.start_date) {
    errors[at("start_date")] = "La fecha de inicio es obligatoria.";
  }
  if (schedule.end_date && schedule.start_date && schedule.end_date < schedule.start_date) {
    errors[at("end_date")] =
      "La fecha de fin no puede ser anterior a la de inicio.";
  }
  return errors;
}

interface ScheduleFormProps {
  value: ScheduleCreateInput;
  onChange: (next: ScheduleCreateInput) => void;
  onRemove?: () => void;
  removable?: boolean;
  errors?: ScheduleErrors;
  errorPrefix?: string;
  disabled?: boolean;
}

export default function ScheduleForm({
  value,
  onChange,
  onRemove,
  removable = false,
  errors = {},
  errorPrefix = "",
  disabled = false,
}: ScheduleFormProps) {
  const err = (field: string) =>
    errors[errorPrefix ? `${errorPrefix}.${field}` : field];

  function set(patch: Partial<ScheduleCreateInput>) {
    onChange({ ...value, ...patch });
  }

  function toggleDay(day: number) {
    const current = value.days_of_week ?? [];
    const next = current.includes(day)
      ? current.filter((item) => item !== day)
      : [...current, day].sort((a, b) => a - b);
    set({ days_of_week: next });
  }

  function setTime(index: number, time: string) {
    const next = value.times.map((item, i) => (i === index ? time : item));
    set({ times: next });
  }

  function addTime() {
    set({ times: [...value.times, "08:00"] });
  }

  function removeTime(index: number) {
    if (value.times.length <= 1) {
      return;
    }
    set({ times: value.times.filter((_, i) => i !== index) });
  }

  return (
    <div className="sched-block">
      <div className="field-row">
        <div className="field">
          <label htmlFor={`freq-${errorPrefix || "nuevo"}`}>
            Frecuencia
          </label>
          <select
            id={`freq-${errorPrefix || "nuevo"}`}
            value={value.frequency}
            disabled={disabled}
            onChange={(event) => {
              const frequency = event.target
                .value as ScheduleFrequency;
              set({
                frequency,
                days_of_week:
                  frequency === "DIAS_SEMANA"
                    ? (value.days_of_week ?? [0])
                    : null,
                interval_days:
                  frequency === "INTERVALO_DIAS"
                    ? (value.interval_days ?? 1)
                    : null,
              });
            }}
          >
            <option value="DIARIO">Todos los días</option>
            <option value="DIAS_SEMANA">Días específicos</option>
            <option value="INTERVALO_DIAS">Cada varios días</option>
          </select>
        </div>

        {value.frequency === "INTERVALO_DIAS" ? (
          <div className="field">
            <label htmlFor={`interval-${errorPrefix || "nuevo"}`}>
              Cada cuántos días
            </label>
            <input
              id={`interval-${errorPrefix || "nuevo"}`}
              type="number"
              min={1}
              step={1}
              value={value.interval_days ?? 1}
              disabled={disabled}
              onChange={(event) =>
                set({
                  interval_days:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
            />
            {err("interval_days") ? (
              <p className="field-error">{err("interval_days")}</p>
            ) : null}
          </div>
        ) : null}
      </div>

      {value.frequency === "DIAS_SEMANA" ? (
        <fieldset className="field day-picker">
          <legend>Días de la semana</legend>
          <div className="day-chips">
            {DAYS.map((label, day) => (
              <label
                key={day}
                className={
                  (value.days_of_week ?? []).includes(day)
                    ? "day-chip active"
                    : "day-chip"
                }
              >
                <input
                  type="checkbox"
                  checked={(value.days_of_week ?? []).includes(day)}
                  disabled={disabled}
                  onChange={() => toggleDay(day)}
                />
                {label}
              </label>
            ))}
          </div>
          {err("days_of_week") ? (
            <p className="field-error">{err("days_of_week")}</p>
          ) : null}
        </fieldset>
      ) : null}

      <div className="field">
        <span className="field-label">Horas de la toma</span>
        {value.times.map((time, index) => (
          <div className="time-row" key={index}>
            <input
              type="time"
              value={time}
              aria-label={`Hora ${index + 1}`}
              disabled={disabled}
              onChange={(event) => setTime(index, event.target.value)}
            />
            {value.times.length > 1 ? (
              <button
                type="button"
                className="btn-ghost"
                disabled={disabled}
                onClick={() => removeTime(index)}
              >
                Quitar
              </button>
            ) : null}
          </div>
        ))}
        <button
          type="button"
          className="btn-ghost"
          disabled={disabled}
          onClick={addTime}
        >
          Añadir hora
        </button>
        {err("times") ? (
          <p className="field-error">{err("times")}</p>
        ) : null}
      </div>

      <div className="field-row">
        <div className="field">
          <label htmlFor={`start-${errorPrefix || "nuevo"}`}>
            Fecha de inicio
          </label>
          <input
            id={`start-${errorPrefix || "nuevo"}`}
            type="date"
            value={value.start_date}
            disabled={disabled}
            onChange={(event) => set({ start_date: event.target.value })}
          />
          {err("start_date") ? (
            <p className="field-error">{err("start_date")}</p>
          ) : null}
        </div>
        <div className="field">
          <label htmlFor={`end-${errorPrefix || "nuevo"}`}>
            Fecha de fin (opcional)
          </label>
          <input
            id={`end-${errorPrefix || "nuevo"}`}
            type="date"
            value={value.end_date ?? ""}
            disabled={disabled}
            onChange={(event) =>
              set({ end_date: event.target.value || null })
            }
          />
          {err("end_date") ? (
            <p className="field-error">{err("end_date")}</p>
          ) : null}
        </div>
      </div>

      {removable && onRemove ? (
        <button
          type="button"
          className="btn-danger"
          disabled={disabled}
          onClick={onRemove}
        >
          Quitar este horario
        </button>
      ) : null}
    </div>
  );
}
