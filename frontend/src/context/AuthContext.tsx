import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  ApiError,
  clearTokens,
  fetchMe,
  getRefreshToken,
  login as loginService,
  logout as logoutService,
  register as registerService,
  restoreSession,
  saveTokens,
  type RegisterInput,
  type UserResponse,
} from "../services/auth";

// Sesion de autenticacion (Fase 8, Entrega 1).
// Unico lugar que conoce al usuario actual: las paginas y el layout
// leen de aqui y nunca llaman a los servicios de auth directamente.
// - login: credenciales -> tokens -> perfil con /me.
// - register: datos -> usuario + tokens (201) -> perfil de la respuesta.
// - logout: revoca el refresh en el backend (si falla, se cierra la
//   sesion local igualmente) y limpia los tokens.
// - Al cargar, restaura la sesion guardada; si el access expiro, el
//   cliente centralizado lo renueva solo con el refresh (rotacion).

interface AuthContextValue {
  user: UserResponse | null;
  loading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  register: (input: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    restoreSession()
      .then((restored) => {
        if (!cancelled) {
          setUser(restored);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        clearTokens();
        setUser(null);
        if (err instanceof ApiError && err.status === 0) {
          setError(err.message);
        } else {
          setError("No se pudo restaurar la sesion.");
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const tokens = await loginService(email, password);
      saveTokens(tokens);
      setUser(await fetchMe());
    },
    [],
  );

  const register = useCallback(async (input: RegisterInput) => {
    const result = await registerService(input);
    saveTokens(result);
    setUser(result.user);
  }, []);

  const logout = useCallback(async () => {
    const refresh = getRefreshToken();
    try {
      if (refresh) {
        await logoutService(refresh);
      }
    } catch {
      // Aunque la revocacion falle (por ejemplo, la sesion ya estaba
      // cerrada), se cierra la sesion local igualmente.
    } finally {
      clearTokens();
      setUser(null);
    }
  }, []);

  const value = useMemo(
    () => ({ user, loading, error, login, register, logout }),
    [user, loading, error, login, register, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth debe usarse dentro de AuthProvider.");
  }
  return context;
}
