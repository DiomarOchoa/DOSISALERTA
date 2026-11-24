// Hora de una toma en grande, con el indicador (a. m. / p. m.) en
// pequeño. La zona horaria es la del usuario (de /me).

import { formatClock } from "../utils/user";

export default function DoseClock({
  value,
  timezone,
  className,
}: {
  value: string;
  timezone: string;
  className?: string;
}) {
  const clock = formatClock(value, timezone);
  return (
    <span className={className}>
      {clock.time}
      <small>{clock.meridiem}</small>
    </span>
  );
}
