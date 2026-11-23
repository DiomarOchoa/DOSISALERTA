// Calendario de tomas (Etapa 5, RF10).
// - Vista de mes (semanas de lunes a domingo, ISO, como la
//   agrupacion semanal de Estadisticas) y vista de semana (las 7
//   tomas de cada dia, en detalle). Cada dia muestra cuantas tomas
//   tiene y su estado (tomadas, pendientes, perdidas, canceladas);
//   al elegir un dia en la vista de mes se ven sus tomas con el
//   mismo detalle que en el Historial.
// - Lee GET /reminders/history para el periodo visible, con
//   paginacion completa (limit 200) para no dejar tomas fuera.
//   Nunca calcula tomas: muestra el estado almacenado tal cual lo
//   devuelve el backend.
// - Las dosis futuras solo existen cuando el sistema las genera
//   (horizonte de 72 h): los dias mas alla de ese horizonte
//   aparecen vacios, sin inventar tomas.

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../services/api";
import { getHistory, type HistoryItem } from "../services/history";
import ApiErrorCard from "../components/ApiErrorCard";
import HistoryRow from "../components/HistoryRow";
import { localDateKey, localDayLabel } from "../utils/user";

const PAGE_SIZE = 200;

const MONTH_NAMES = [
  "Enero",
  "Febrero",
  "Marzo",
  "Abril",
  "Mayo",
  "Junio",
  "Julio",
  "Agosto",
  "Septiembre",
  "Octubre",
  "Noviembre",
  "Diciembre",
];

const WEEKDAY_NAMES = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];

function dateKey(year: number, month: number, day: number): string {
  return `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

function parseKey(key: string): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(key);
  if (!match) {
    return null;
  }
  return new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
}

function addDays(key: string, days: number): string {
  const date = parseKey(key);
  if (!date) {
    return key;
  }
  date.setDate(date.getDate() + days);
  return dateKey(date.getFullYear(), date.getMonth(), date.getDate());
}

// Lunes de la semana que contiene la fecha dada.
function mondayOf(key: string): string {
  const date = parseKey(key);
  if (!date) {
    return key;
  }
  const offset = (date.getDay() + 6) % 7;
  date.setDate(date.getDate() - offset);
  return dateKey(date.getFullYear(), date.getMonth(), date.getDate());
}

// Inicio de un dia local como datetime ISO (UTC), para el filtro
// from/to del backend, que usa [from, to) sobre scheduled_at.
function localDayStartIso(key: string): string {
  const date = parseKey(key);
  if (!date) {
    return key;
  }
  return date.toISOString();
}

function addMonths(year: number, month: number, delta: number) {
  const date = new Date(year, month + delta, 1);
  return { year: date.getFullYear(), month: date.getMonth() };
}

// Etiqueta corta de un dia para el titulo de la semana:
// "lun 16 nov". Evita el "Hoy"/"Mañana" de localDayLabel, que
// no encaja en un rango de fechas.
function shortDayLabel(key: string): string {
  const date = parseKey(key);
  if (!date) {
    return key;
  }
  const label = date.toLocaleDateString("es-CO", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  return label.charAt(0).toUpperCase() + label.slice(1);
}

interface DaySummary {
  taken: number;
  pending: number;
  lost: number;
  cancelled: number;
  other: number;
}

function summarize(items: HistoryItem[]): DaySummary {
  const summary: DaySummary = {
    taken: 0,
    pending: 0,
    lost: 0,
    cancelled: 0,
    other: 0,
  };
  for (const item of items) {
    if (item.status === "TOMADA") {
      summary.taken++;
    } else if (
      item.status === "PENDIENTE" ||
      item.status === "ENVIANDO" ||
      item.status === "ENVIADA"
    ) {
      summary.pending++;
    } else if (item.status === "PERDIDA") {
      summary.lost++;
    } else if (item.status === "CANCELADA") {
      summary.cancelled++;
    } else {
      summary.other++;
    }
  }
  return summary;
}

export default function CalendarPage() {
  const { user } = useAuth();
  const timezone = user?.timezone ?? "America/Bogota";
  const today = new Date();
  const todayKey = dateKey(
    today.getFullYear(),
    today.getMonth(),
    today.getDate(),
  );
  const [view, setView] = useState<"month" | "week">("month");
  const [year, setYear] = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth());
  const [weekStart, setWeekStart] = useState(() => mondayOf(todayKey));
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);

  const firstKey = dateKey(year, month, 1);
  const next = addMonths(year, month, 1);
  const lastKey = dateKey(next.year, next.month, 1);
  const weekEnd = addDays(weekStart, 7);
  const rangeFrom = view === "month" ? firstKey : weekStart;
  const rangeTo = view === "month" ? lastKey : weekEnd;

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const all: HistoryItem[] = [];
        let offset = 0;
        let total = 0;
        do {
          const page = await getHistory({
            from: localDayStartIso(rangeFrom),
            to: localDayStartIso(rangeTo),
            limit: PAGE_SIZE,
            offset,
          });
          total = page.total;
          all.push(...page.items);
          offset += page.items.length;
        } while (offset < total);
        if (cancelled) {
          return;
        }
        setItems(all);
        setSelectedDay((current) => {
          if (current && current >= rangeFrom && current < rangeTo) {
            return current;
          }
          return todayKey >= rangeFrom && todayKey < rangeTo
            ? todayKey
            : rangeFrom;
        });
      } catch (caught) {
        if (cancelled) {
          return;
        }
        setError(
          caught instanceof ApiError
            ? caught
            : new ApiError(0, "No se pudo cargar el calendario."),
        );
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
    // rangeFrom/rangeTo resumen vista + periodo; todayKey es
    // estable dentro del dia.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rangeFrom, rangeTo]);

  const byDay = new Map<string, HistoryItem[]>();
  for (const item of items) {
    const key = localDateKey(item.scheduled_at, timezone);
    const list = byDay.get(key) ?? [];
    list.push(item);
    byDay.set(key, list);
  }

  const daysInMonth = new Date(year, month + 1, 0).getDate();
  // Desplazamiento del dia 1: lunes = 0, domingo = 6.
  const firstWeekday = (new Date(year, month, 1).getDay() + 6) % 7;
  const cells: (string | null)[] = [];
  for (let i = 0; i < firstWeekday; i++) {
    cells.push(null);
  }
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push(dateKey(year, month, day));
  }
  while (cells.length % 7 !== 0) {
    cells.push(null);
  }

  const weekDays: string[] = [];
  for (let i = 0; i < 7; i++) {
    weekDays.push(addDays(weekStart, i));
  }
  const weekLabel = `${shortDayLabel(weekStart)} – ${shortDayLabel(addDays(weekStart, 6))}`;

  const selectedItems = selectedDay ? (byDay.get(selectedDay) ?? []) : [];

  function goMonth(delta: number) {
    const target = addMonths(year, month, delta);
    setYear(target.year);
    setMonth(target.month);
  }

  function goWeek(delta: number) {
    setWeekStart((current) => addDays(current, delta * 7));
  }

  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
    setWeekStart(mondayOf(todayKey));
    setSelectedDay(todayKey);
  }

  if (loading) {
    return (
      <div>
        <div className="page-head">
          <h2>Calendario</h2>
        </div>
        <p className="hint">Cargando el calendario…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <div className="page-head">
          <h2>Calendario</h2>
        </div>
        <ApiErrorCard
          error={error}
          onRetry={() => (view === "month" ? goMonth(0) : goWeek(0))}
        />
      </div>
    );
  }

  return (
    <div>
      <div className="page-head">
        <h2>Calendario</h2>
      </div>
      <p className="hint">
        Tus tomas por día. Las dosis futuras aparecen solo cuando el
        sistema las genera (hasta 72 horas antes), así que los días
        más lejanos se ven vacíos.
      </p>

      <div className="tabs">
        <button
          type="button"
          className={view === "month" ? "tab active" : "tab"}
          onClick={() => setView("month")}
        >
          Mes
        </button>
        <button
          type="button"
          className={view === "week" ? "tab active" : "tab"}
          onClick={() => setView("week")}
        >
          Semana
        </button>
      </div>

      {view === "month" ? (
        <section className="card">
          <div className="calendar-nav">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => goMonth(-1)}
              aria-label="Mes anterior"
            >
              ‹
            </button>
            <h3>
              {MONTH_NAMES[month]} de {year}
            </h3>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => goMonth(1)}
              aria-label="Mes siguiente"
            >
              ›
            </button>
            <button type="button" className="btn-ghost" onClick={goToday}>
              Hoy
            </button>
          </div>

          <div className="calendar-grid" role="grid">
            {WEEKDAY_NAMES.map((name) => (
              <div key={name} className="calendar-weekday">
                {name}
              </div>
            ))}
            {cells.map((key, index) => {
              if (key === null) {
                return (
                  <div
                    key={`vacio-${index}`}
                    className="calendar-day empty"
                  />
                );
              }
              const dayItems = byDay.get(key) ?? [];
              const summary = summarize(dayItems);
              const dayNumber = Number(key.slice(-2));
              const isToday = key === todayKey;
              const isSelected = key === selectedDay;
              return (
                <button
                  key={key}
                  type="button"
                  className={[
                    "calendar-day",
                    isToday ? "today" : "",
                    isSelected ? "selected" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => setSelectedDay(key)}
                  aria-label={`${localDayLabel(key, todayKey)}: ${dayItems.length} tomas`}
                >
                  <span className="calendar-day-number">{dayNumber}</span>
                  {dayItems.length > 0 ? (
                    <span className="calendar-dots">
                      {summary.taken > 0 ? (
                        <span className="dot dot-taken" title="Tomadas">
                          {summary.taken}
                        </span>
                      ) : null}
                      {summary.pending > 0 ? (
                        <span className="dot dot-pending" title="Pendientes">
                          {summary.pending}
                        </span>
                      ) : null}
                      {summary.lost > 0 ? (
                        <span className="dot dot-lost" title="Perdidas">
                          {summary.lost}
                        </span>
                      ) : null}
                      {summary.cancelled > 0 ? (
                        <span
                          className="dot dot-cancelled"
                          title="Canceladas"
                        >
                          {summary.cancelled}
                        </span>
                      ) : null}
                      {summary.other > 0 ? (
                        <span className="dot dot-other" title="Otras">
                          {summary.other}
                        </span>
                      ) : null}
                    </span>
                  ) : null}
                </button>
              );
            })}
          </div>

          {items.length === 0 ? (
            <p className="hint" style={{ marginTop: "1rem" }}>
              Sin dosis en este mes.
            </p>
          ) : null}
        </section>
      ) : (
        <section className="card">
          <div className="calendar-nav">
            <button
              type="button"
              className="btn-ghost"
              onClick={() => goWeek(-1)}
              aria-label="Semana anterior"
            >
              ‹
            </button>
            <h3>{weekLabel}</h3>
            <button
              type="button"
              className="btn-ghost"
              onClick={() => goWeek(1)}
              aria-label="Semana siguiente"
            >
              ›
            </button>
            <button type="button" className="btn-ghost" onClick={goToday}>
              Hoy
            </button>
          </div>

          {items.length === 0 ? (
            <p className="hint">Sin dosis en esta semana.</p>
          ) : null}
          {weekDays.map((key) => {
            const dayItems = byDay.get(key) ?? [];
            if (dayItems.length === 0) {
              return null;
            }
            return (
              <div key={key} className="day-group">
                <h3 className="day-title">
                  {localDayLabel(key, todayKey)} · {dayItems.length}{" "}
                  {dayItems.length === 1 ? "toma" : "tomas"}
                </h3>
                <ul className="upcoming-list">
                  {dayItems.map((item) => (
                    <HistoryRow
                      key={item.id}
                      item={item}
                      timezone={timezone}
                    />
                  ))}
                </ul>
              </div>
            );
          })}
        </section>
      )}

      {view === "month" && selectedDay ? (
        <section className="card">
          <h3>
            {localDayLabel(selectedDay, todayKey)}
            {selectedItems.length > 0
              ? ` · ${selectedItems.length} ${selectedItems.length === 1 ? "toma" : "tomas"}`
              : ""}
          </h3>
          {selectedItems.length === 0 ? (
            <p className="hint">Sin tomas este día.</p>
          ) : (
            <ul className="upcoming-list">
              {selectedItems.map((item) => (
                <HistoryRow
                  key={item.id}
                  item={item}
                  timezone={timezone}
                />
              ))}
            </ul>
          )}
          <p className="hint">
            <Link to="/historial">Ver todo el historial</Link>
          </p>
        </section>
      ) : null}
    </div>
  );
}
