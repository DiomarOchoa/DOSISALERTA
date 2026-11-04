# Frontend — DosisAlerta (React + Vite + TypeScript)

> Estado: **Fase 1 — implementada, pendiente de revisión.**
> Ya existe el proyecto Vite + React + TypeScript con una pantalla
> inicial que comprueba el backend. Todavia NO hay inicio de sesion,
> medicamentos, tratamientos ni ninguna vista funcional: eso llega
> en las Fases 3, 4 y 8. No se ha hecho ningun commit.

## Decisión ya tomada: TypeScript, no JavaScript plano

Ver la justificación completa en `docs/decisions/DECISIONES_TECNICAS.md`.
Resumen: los tipos detectan errores de contrato con la API antes de
ejecutar, facilitan el refactor y hacen el código más defendible en
sustentación, con un coste de aprendizaje bajo porque Vite ya lo
soporta sin configuración extra.

## Lo que ya existe (Fase 1)

```text
frontend/
├── package.json          # React 19, Vite 6, TypeScript 5
├── vite.config.ts        # Puerto 5173, plugin React
├── tsconfig.json         # Modo estricto, jsx: react-jsx
├── index.html            # Titulo DosisAlerta, punto de montaje
├── .env.example          # VITE_API_URL (copiar a .env)
└── src/
    ├── main.tsx          # Punto de entrada (StrictMode)
    ├── App.tsx           # Pantalla inicial + comprobacion de /health
    ├── styles.css        # CSS minimo con variables, sin framework
    ├── vite-env.d.ts     # Tipos de import.meta.env
    ├── components/       # Reservado: componentes reutilizables
    ├── pages/            # Reservado: vistas (Fases 3, 4, 8)
    ├── services/         # Reservado: cliente HTTP de la API
    ├── hooks/            # Reservado: logica compartida
    ├── context/          # Reservado: sesion del usuario (Fase 3)
    └── styles/           # Reservado: estilos por modulo
```

La pantalla inicial muestra que es DosisAlerta, la URL de la API
configurada y un boton "Comprobar backend" que llama a
`GET /api/v1/health`. Si el backend no esta levantado, muestra un
mensaje claro en lugar de fallar en silencio. No es un modulo
funcional: no hay formularios de medicamentos ni de tratamientos.

## Ejecucion (Fase 1)

### Windows PowerShell

```powershell
cd frontend
npm install
Copy-Item .env.example .env
npm run dev
```

### Linux / macOS

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

- Web en http://localhost:5173
- Compilacion: `npm run build` (primero `tsc` en modo estricto,
  luego `vite build`). Si hay un error de tipos, el build falla:
  eso es intencionado, no un detalle a ignorar.
- Vista previa del build: `npm run preview` (opcional).

## Variables de entorno (importante)

Vite **solo** lee variables que empiezan por `VITE_` y **solo** desde
la carpeta `frontend/`. Por eso existe `frontend/.env.example`,
ademas del `.env.example` de la raiz (que es para backend y Docker).

```text
VITE_API_URL=http://localhost:8000/api/v1
```

- `VITE_API_URL` es la URL base de la API. La pantalla inicial
  construye la URL de salud a partir de ella: si termina en
  `/api/v1`, usa `<base>/health`; si no, usa `<base>/api/v1/health`.
- No hay secretos en `.env.example`: solo una URL local. El `.env`
  real nunca se sube a Git (esta en `.gitignore`).

## Versiones verificadas en la Fase 1

Probadas en el entorno de desarrollo de la Fase 1 (Node.js 24.22.1,
npm 10.9.4):

| Dependencia | Version instalada |
|---|---|
| React / React DOM | 19.3.1 |
| Vite | 6.4.5 |
| TypeScript | 5.9.3 |
| @vitejs/plugin-react | 4.7.0 |

## Reglas que ya estan decididas

- El frontend nunca inventa reglas de negocio: toda regla vive en el
  backend Python. Si la web y Telegram discrepan, manda el backend.
- Toda llamada va a `/api/v1/...` con el token JWT en el encabezado
  (a partir de la Fase 3; en la Fase 1 no hay token porque no hay
  autenticacion).
- No hay WebSocket en esta version: la web recarga los datos despues
  de cada accion y al entrar a cada vista. Anadir tiempo real seria
  una tecnologia innecesaria para los requisitos actuales.
