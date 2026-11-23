# Frontend — DosisAlerta (React + Vite + TypeScript)

> Estado: **Fases 1–8 completadas, Fase 9 en curso (2026-11-22).**
> La web está completa: registro e inicio de sesión, medicamentos,
> tratamientos con horarios, próximas tomas (confirmar y posponer),
> calendario, historial, estadísticas, perfil con zona horaria y
> cuidadores. Build en verde: **83 módulos**, `tsc` estricto,
> JS **380,60 kB** (gzip 110,85 kB), CSS **15,31 kB**.
> Entrega del proyecto: **25 de noviembre de 2026, 12:00**.

## Historia: Fases 1 y 2

El proyecto se creó en la Fase 1 como Vite + React + TypeScript
con una pantalla inicial que comprobaba el backend
(`GET /api/v1/health`, botón "Comprobar backend"). Esa pantalla
ya no existe: fue sustituida por el inicio de sesión (Fase 3) y
el panel principal (Fase 8). Commits de aquella época en `main`:
`2bc7ec8` (implementación, 2026-11-04), `77d0d5c` (auditoría y
fijación de dependencias, 2026-11-04), `819c44b` (correcciones,
2026-11-04), `e8d4f0e` (decisiones, 2026-11-11) y `5f75de0`
(Fase 2, 2026-11-11).

## Decisión ya tomada: TypeScript, no JavaScript plano

Ver la justificación completa en `docs/decisions/DECISIONES_TECNICAS.md`.
Resumen: los tipos detectan errores de contrato con la API antes de
ejecutar, facilitan el refactor y hacen el código más defendible en
sustentación, con un coste de aprendizaje bajo porque Vite ya lo
soporta sin configuración extra.

## Estructura real de `src/` (Fases 1–8)

```text
frontend/
├── package.json          # React 19, react-router-dom 7, Vite 6, TypeScript 5
├── vite.config.ts        # Puerto 5173, plugin React
├── tsconfig.json         # Modo estricto, jsx: react-jsx
├── index.html            # Titulo DosisAlerta, punto de montaje
├── .env.example          # VITE_API_URL (copiar a .env)
└── src/
    ├── main.tsx          # Punto de entrada (StrictMode)
    ├── App.tsx           # Rutas (ver abajo)
    ├── config.ts         # URL base de la API
    ├── styles.css        # CSS con variables AppSalud, sin framework
    ├── vite-env.d.ts     # Tipos de import.meta.env
    ├── components/
    │   ├── ApiErrorCard.tsx      # Tarjeta de error de la API
    │   ├── HistoryRow.tsx        # Una fila del historial (8 estados)
    │   ├── Layout.tsx            # Cabecera + navegación inferior
    │   ├── LoginForm.tsx / RegisterForm.tsx
    │   ├── MedicationForm.tsx / TreatmentForm.tsx
    │   │   └── TreatmentMedicationForm.tsx / ScheduleForm.tsx
    │   ├── ProtectedRoute.tsx    # Guarda de rutas con sesión
    │   ├── StatsBarChart.tsx / StatsSummary.tsx
    │   ├── StatusBadge.tsx       # Insignia de estado de toma
    │   ├── UpcomingReminders.tsx # Próximas tomas (confirmar/posponer)
    │   ├── icons.tsx             # Home, Pill, Calendar, Bell, Clock,
    │   │                         # User, Chart
    │   └── ModuleSoon.tsx        # Código muerto preexistente: no lo
    │                             # importa nada; no se borra sin
    │                             # autorización del equipo
    ├── pages/
    │   ├── DashboardPage.tsx     # /inicio
    │   ├── MedicationsPage.tsx / MedicationCreatePage.tsx
    │   │   └── MedicationDetailPage.tsx
    │   ├── TreatmentsPage.tsx / TreatmentCreatePage.tsx
    │   │   └── TreatmentDetailPage.tsx
    │   ├── RemindersPage.tsx     # /recordatorios
    │   ├── HistoryPage.tsx       # /historial
    │   ├── StatsPage.tsx         # /estadisticas
    │   ├── ProfilePage.tsx       # /perfil (zona horaria)
    │   ├── CaregiversPage.tsx    # /cuidadores
    │   ├── CalendarPage.tsx      # /calendario (mes y semana)
    │   ├── LoginPage.tsx / RegisterPage.tsx
    │   └── NotFoundPage.tsx
    ├── services/                 # Un servicio por dominio, sobre
    │   │                         # request() con { auth: true }
    │   ├── api.ts                # Cliente HTTP, refresco de token
    │   ├── auth.ts               # Registro, login, logout, perfil
    │   ├── medications.ts        # CRUD + desactivar + reactivar
    │   ├── treatments.ts         # CRUD + estados + próximas tomas
    │   ├── history.ts            # Historial paginado con filtros
    │   ├── stats.ts              # Cumplimiento con group_by
    │   ├── reminders.ts          # Confirmar y posponer (15/30/60)
    │   └── caregivers.ts         # Invitaciones, permisos, auditoría
    ├── context/
    │   └── AuthContext.tsx       # Sesión del usuario (login,
    │                             # register, logout, refreshUser)
    ├── hooks/                    # Reservado: lógica compartida
    └── utils/
        └── user.ts               # Formato de fechas en la zona
                                  # del usuario (es-CO)
```

## Rutas

Rutas públicas (redirigen a `/inicio` si ya hay sesión):

| Ruta | Vista |
|---|---|
| `/login` | Inicio de sesión |
| `/registro` | Registro |

Rutas protegidas (bajo `ProtectedRoute` + `AppLayout`; `/`
redirige a `/inicio`):

| Ruta | Vista |
|---|---|
| `/inicio` | Panel principal (próxima toma, acciones rápidas) |
| `/medicamentos`, `/medicamentos/nuevo`, `/medicamentos/:id` | Catálogo de medicamentos |
| `/tratamientos`, `/tratamientos/nuevo`, `/tratamientos/:id` | Tratamientos y horarios |
| `/recordatorios` | Próximas tomas |
| `/historial` | Historial completo (8 estados, filtros, paginación) |
| `/estadisticas` | Cumplimiento (día/semana/mes/medicamento) |
| `/perfil` | Perfil y zona horaria |
| `/cuidadores` | Mis cuidadores / Soy cuidador de |
| `/calendario` | Calendario de tomas (mes y semana) |
| `*` | Página no encontrada |

La navegación inferior tiene 5 ítems (Inicio, Medicamentos,
Tratamientos, Recordatorios, Perfil) y **no se modifica** por
decisión del equipo. Las demás vistas se alcanzan desde el panel
o desde enlaces dentro de cada vista.

## Ejecución

### Windows PowerShell

```powershell
cd frontend
npm ci
Copy-Item .env.example .env
npm run dev
```

### Linux / macOS

```bash
cd frontend
npm ci
cp .env.example .env
npm run dev
```

- Web en http://localhost:5173 (el backend debe correr en
  http://localhost:8000; ver `docs/GUIA_INSTALACION_WINDOWS.md`).
- Compilación: `npm run build` (primero `tsc` en modo estricto,
  luego `vite build`). Si hay un error de tipos, el build falla:
  eso es intencionado, no un detalle a ignorar.
- Vista previa del build: `npm run preview` (opcional).

## Variables de entorno (importante)

Vite **solo** lee variables que empiezan por `VITE_` y **solo** desde
la carpeta `frontend/`. Por eso existe `frontend/.env.example`,
además del `.env.example` de la raíz (que es para backend y Docker).

```text
VITE_API_URL=http://localhost:8000/api/v1
```

- `VITE_API_URL` es la URL base de la API. No hay secretos en
  `.env.example`: solo una URL local. El `.env` real nunca se
  sube a Git (está en `.gitignore`).

## Versiones verificadas

Versiones canónicas fijadas en la Fase A (`.nvmrc`, `engines` en
`package.json` y `engine-strict` en `.npmrc`): Node.js 24.12.0 y
npm 11.6.2, verificadas en el PC del equipo con `npm ci` y
`npm run build` correctos. Las versiones exactas de las dependencias
son las de la tabla:

| Dependencia | Version instalada |
|---|---|
| React / React DOM | 19.3.1 |
| react-router-dom | 7.18.6 |
| Vite | 6.4.5 |
| TypeScript | 5.9.3 |
| @vitejs/plugin-react | 4.7.0 |

Reproducibilidad: las versiones exactas están fijadas en
`package-lock.json`. Para una instalación exactamente igual a la
bloqueada, usar `npm ci` en lugar de `npm install`; `npm install`
puede actualizar el bloqueo si se cambian los rangos de
`package.json`.

## Cómo se verifica el frontend (no hay tests unitarios)

No hay tests de frontend. La verificación se hace con **7 harnesses
jsdom** que renderizan los componentes reales contra la **API real**
y comprueban el DOM renderizado (filtros, paginación, botones,
estados vacíos, errores). Estado actual (Etapa 7, 2026-11-22):
**7 harnesses en verde** (historial, estadísticas, navegación,
reactivar/confirmar/posponer, cuidadores, calendario, zona
horaria). Los harnesses viven fuera del repositorio del frontend
y comparan contra la base de desarrollo, así que sus conteos
absolutos (filas de historial, grupos de estadísticas) cambian
cuando la verificación confirma o pospone tomas reales: lo que
se verifica es el comportamiento, no el número absoluto.

**Pendiente:** la comprobación visual a 390 px sigue pendiente
en el PC (el Chromium de la máquina virtual bloquea la
navegación a la red local y no puede abrir `localhost:5173`).

## Reglas que ya están decididas

- El frontend nunca inventa reglas de negocio: toda regla vive en el
  backend Python. Si la web y Telegram discrepan, manda el backend.
- Toda llamada va a `/api/v1/...` con el token JWT en el encabezado.
  Si el token caduca, el cliente intenta un refresco y, si falla,
  cierra la sesión.
- No hay librerías externas de gráficas, fechas, estado ni tablas:
  las gráficas de estadísticas son barras CSS, las fechas se
  formatean con `Intl` del navegador y el estado vive en
  `AuthContext` y en recargas tras cada acción.
- No hay WebSocket en esta versión: la web recarga los datos después
  de cada acción y al entrar a cada vista. Añadir tiempo real sería
  una tecnología innecesaria para los requisitos actuales.
- La web **no** tiene pantalla de vinculación de Telegram (Fase 8):
  la vinculación se hace con el código generado por la API y el
  comando `/vincular` del bot (ver
  `docs/bot/CONFIGURACION_TELEGRAM.md`). Desde el bot **no** se
  puede crear un tratamiento (RF18 parcial): solo desde la web.
- El botón "NO LO HE TOMADO" no existe y no debe implementarse:
  fue eliminado definitivamente el 2026-11-11. Confirmar una toma
  es solo el botón "Tomada"; posponer ofrece 15, 30 o 60 minutos.
