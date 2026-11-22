// Utilidades de presentacion del usuario (Fase 8, Entrega 1).
// Compartidas por el layout (chip de usuario) y el perfil.

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  const first = parts[0]?.charAt(0) ?? "";
  const second = parts.length > 1 ? parts[1].charAt(0) : "";
  return (first + second).toUpperCase();
}

export function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString("es-CO", {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// Fecha y hora de un instante UTC, mostradas en la zona horaria
// del usuario (IANA, por ejemplo America/Bogota). Si la zona no es
// valida, se usa la zona local del navegador.
export function formatInZone(value: string, timezone: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  try {
    return date.toLocaleString("es-CO", {
      timeZone: timezone,
      dateStyle: "medium",
      timeStyle: "short",
    });
  } catch {
    return formatDate(value);
  }
}

// Fecha "YYYY-MM-DD" sin hora (por ejemplo, el inicio de un
// tratamiento): se interpreta como fecha local, no como medianoche
// UTC, para que no se desplace un dia al mostrarla.
export function formatDateOnly(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!match) {
    return formatDate(value);
  }
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  return date.toLocaleDateString("es-CO", { dateStyle: "medium" });
}

// Clave de día local "YYYY-MM-DD" de un instante UTC, en la zona
// horaria del usuario (IANA, por ejemplo America/Bogota).
// Imprescindible para agrupar las próximas tomas por día: la fecha
// UTC no es la fecha que ve el usuario (una toma a las 02:00 UTC
// es el día anterior en Bogotá). Si la zona no es válida, se usa
// la zona local del navegador.
export function localDateKey(value: string, timezone: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  try {
    const parts = new Intl.DateTimeFormat("es-CO", {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const get = (type: string): string =>
      parts.find((part) => part.type === type)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")}`;
  } catch {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
  }
}

// Etiqueta de un día local para los grupos de próximas tomas:
// "Hoy", "Mañana" o la fecha con día de semana (por ejemplo,
// "Lunes, 24 de noviembre"). `todayKey` es la clave del día actual
// en la misma zona horaria, calculada con `localDateKey`.
export function localDayLabel(dayKey: string, todayKey: string): string {
  if (dayKey === todayKey) {
    return "Hoy";
  }
  const todayMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(todayKey);
  if (todayMatch) {
    const tomorrow = new Date(
      Number(todayMatch[1]),
      Number(todayMatch[2]) - 1,
      Number(todayMatch[3]) + 1,
    );
    const year = tomorrow.getFullYear();
    const month = String(tomorrow.getMonth() + 1).padStart(2, "0");
    const day = String(tomorrow.getDate()).padStart(2, "0");
    if (dayKey === `${year}-${month}-${day}`) {
      return "Mañana";
    }
  }
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dayKey);
  if (!match) {
    return dayKey;
  }
  const date = new Date(
    Number(match[1]),
    Number(match[2]) - 1,
    Number(match[3]),
  );
  // "martes, 24 de noviembre": se pone en mayúscula la primera
  // letra para usarlo como título de grupo.
  const text = date.toLocaleDateString("es-CO", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  return text.charAt(0).toUpperCase() + text.slice(1);
}
