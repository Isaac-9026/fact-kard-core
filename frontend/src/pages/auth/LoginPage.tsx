import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  Loader2,
  Eye,
  EyeOff,
  Info,
  X,
} from 'lucide-react'
import { useAuth } from '../../context/useAuth'
import { RUTA_INICIAL } from '../../navegacion'
import { loginApi } from '../../api/auth'
import type { AxiosError } from 'axios'
import { Button } from '../../components/ui/button'
import { Input } from '../../components/ui/input'
import { Label } from '../../components/ui/label'

const STORAGE_KEY_RECORDAR = 'fk_recordar_usuario'

export const LoginPage: React.FC = () => {
  const [username, setUsername] = useState(() => {
    return localStorage.getItem(STORAGE_KEY_RECORDAR) || 'admin_demo'
  })
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [recordarUsuario, setRecordarUsuario] = useState(() => {
    return localStorage.getItem(STORAGE_KEY_RECORDAR) !== null
  })
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [infoMsg, setInfoMsg] = useState<React.ReactNode | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [capsLockActive, setCapsLockActive] = useState(false)

  const { login } = useAuth()
  const navigate = useNavigate()

  const handleUsernameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setUsername(e.target.value)
    if (errorMsg) setErrorMsg(null)
    if (infoMsg) setInfoMsg(null)
  }

  const handlePasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPassword(e.target.value)
    if (errorMsg) setErrorMsg(null)
    if (infoMsg) setInfoMsg(null)
  }

  const handlePasswordKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    setCapsLockActive(e.getModifierState('CapsLock'))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErrorMsg(null)
    setInfoMsg(null)

    const userTrim = username.trim()
    if (!userTrim || !password) {
      setErrorMsg('Por favor ingrese su usuario y contraseña.')
      return
    }

    try {
      setIsLoading(true)
      const data = await loginApi({
        username: userTrim,
        password,
      })

      if (recordarUsuario) {
        localStorage.setItem(STORAGE_KEY_RECORDAR, userTrim)
      } else {
        localStorage.removeItem(STORAGE_KEY_RECORDAR)
      }

      login(data.token ?? null, data.usuario, data.empresas)
      navigate(RUTA_INICIAL)
    } catch (err) {
      const axiosError = err as AxiosError<{ detail?: string }>
      if (axiosError.response?.data?.detail) {
        setErrorMsg(axiosError.response.data.detail)
      } else if (axiosError.message === 'Network Error') {
        setErrorMsg('Error de conexión: No se pudo contactar al servidor backend.')
      } else {
        setErrorMsg('Credenciales incorrectas. Verifique su usuario y contraseña.')
      }
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2 font-sans bg-white selection:bg-slate-950 selection:text-white">
      {/* Columna Izquierda: Formulario estructurado exactamente según tu referencia */}
      <div className="flex flex-col justify-between py-6 sm:py-8 lg:py-10 px-6 sm:px-10 lg:px-12 xl:px-14 bg-white">
        
        {/* 1. Logotipo Superior Izquierdo */}
        <div>
          <a
            href="#"
            onClick={(e) => e.preventDefault()}
            className="inline-flex items-center gap-2.5 transition-opacity hover:opacity-90 active:scale-[0.99] w-fit"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-950 p-1.5 text-white shadow-xs">
              <svg
                viewBox="0 0 16 16"
                fill="none"
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5 text-white"
                aria-hidden="true"
              >
                <path
                  d="M3 1L0 4V5C0 5 2 6 4 6C6 6 8 5 8 5C8 5 10 6 12 6C14 6 16 5 16 5V4L13 1H3Z"
                  fill="currentColor"
                />
                <path
                  fillRule="evenodd"
                  clipRule="evenodd"
                  d="M1 15V7.5187C1.81671 7.76457 2.88168 8 4 8C5.3025 8 6.53263 7.68064 7.38246 7.39737C7.60924 7.32177 7.81664 7.24612 8 7.17526C8.18337 7.24612 8.39076 7.32177 8.61754 7.39737C9.46737 7.68064 10.6975 8 12 8C13.1183 8 14.1833 7.76457 15 7.5187V15H7V10H4V15H1ZM12 10H10V13H12V10Z"
                  fill="currentColor"
                />
              </svg>
            </div>
            <span className="text-xl font-bold tracking-tight text-slate-950">
              FACT-KARD
            </span>
          </a>
        </div>

        {/* 2. Cuerpo Central: Encabezado Centrado + Formulario con Espaciado Fiel a la Referencia */}
        <div className="w-full max-w-sm sm:max-w-[400px] lg:max-w-[420px] 2xl:max-w-[440px] mx-auto my-auto py-4 sm:py-6">
          <div className="text-center mb-7">
            <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-slate-950">
              Bienvenido de nuevo
            </h1>
            <p className="text-xs sm:text-sm text-slate-500 mt-2">
              Ingrese su usuario y contraseña para acceder a su cuenta.
            </p>
          </div>

          {/* Mensaje de Error */}
          {errorMsg && (
            <div
              className="mb-5 flex items-start gap-2.5 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 animate-in fade-in duration-150"
              role="alert"
            >
              <AlertCircle className="h-4 w-4 shrink-0 text-rose-600 mt-0.5" />
              <span className="font-medium leading-relaxed">{errorMsg}</span>
            </div>
          )}

          {/* Mensaje Informativo (Restablecer contraseña / Soporte) */}
          {infoMsg && (
            <div
              className="mb-5 flex items-start gap-2.5 rounded-lg border border-sky-200 bg-sky-50 p-3 text-xs text-sky-800 animate-in fade-in duration-150"
              role="status"
            >
              <Info className="h-4 w-4 shrink-0 text-sky-600 mt-0.5" />
              <span className="flex-1 font-medium leading-relaxed">{infoMsg}</span>
              <button
                type="button"
                onClick={() => setInfoMsg(null)}
                className="text-sky-500 hover:text-sky-800 transition-colors p-0.5 rounded cursor-pointer"
                aria-label="Cerrar mensaje"
                title="Cerrar"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4" noValidate>
            {/* Campo Usuario o Email */}
            <div className="space-y-1.5 text-left">
              <Label
                htmlFor="username-input"
                required
                className="text-xs font-semibold text-slate-700"
              >
                Usuario o Email
              </Label>
              <div className="relative">
                <Input
                  id="username-input"
                  type="text"
                  autoComplete="username"
                  autoFocus={!username}
                  value={username}
                  onChange={handleUsernameChange}
                  placeholder="admin_demo"
                  required
                  disabled={isLoading}
                  className={`h-10 rounded-lg bg-white text-slate-900 placeholder:text-slate-400 text-sm shadow-2xs transition-colors duration-150 ${
                    errorMsg
                      ? 'border-rose-300 focus:border-rose-500 focus:ring-2 focus:ring-rose-500/15'
                      : 'border-slate-200 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/15'
                  }`}
                />
              </div>
            </div>

            {/* Campo Contraseña */}
            <div className="space-y-1.5 text-left">
              <Label
                htmlFor="password-input"
                required
                className="text-xs font-semibold text-slate-700"
              >
                Contraseña
              </Label>
              <div className="relative">
                <Input
                  id="password-input"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  autoFocus={Boolean(username)}
                  value={password}
                  onChange={handlePasswordChange}
                  placeholder="••••••••"
                  required
                  disabled={isLoading}
                  onKeyDown={handlePasswordKey}
                  onKeyUp={handlePasswordKey}
                  onBlur={() => setCapsLockActive(false)}
                  className={`pr-10 h-10 rounded-lg bg-white text-slate-900 placeholder:text-slate-400 text-sm shadow-2xs transition-colors duration-150 font-mono ${
                    errorMsg
                      ? 'border-rose-300 focus:border-rose-500 focus:ring-2 focus:ring-rose-500/15'
                      : 'border-slate-200 focus:border-slate-950 focus:ring-2 focus:ring-slate-950/15'
                  }`}
                />
                <button
                  type="button"
                  tabIndex={-1}
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute inset-y-0 right-0 flex items-center pr-3 text-slate-400 hover:text-slate-700 transition-colors duration-150 active:scale-90 motion-safe:transition-transform cursor-pointer outline-none focus-visible:text-slate-950"
                  title={showPassword ? 'Ocultar contraseña' : 'Ver contraseña'}
                  aria-label={showPassword ? 'Ocultar contraseña' : 'Ver contraseña'}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
              {capsLockActive && (
                <div className="flex items-center gap-1.5 text-[11px] text-amber-700 font-medium animate-in fade-in duration-150 pt-0.5">
                  <span className="inline-flex items-center justify-center h-3.5 w-3.5 rounded bg-amber-100 text-amber-800 font-bold text-[9px]">
                    ⇪
                  </span>
                  <span>Bloq Mayús está activado</span>
                </div>
              )}
            </div>

            {/* Fila: Recordar credenciales (izq) + ¿Olvidó su contraseña? (der) */}
            <div className="flex items-center justify-between text-xs pt-1">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={recordarUsuario}
                  onChange={(e) => setRecordarUsuario(e.target.checked)}
                  className="h-4 w-4 rounded border-slate-300 text-slate-950 focus:ring-slate-950/20 accent-slate-950 cursor-pointer"
                />
                <span className="text-slate-600 font-medium">Recordar credenciales</span>
              </label>

              <button
                type="button"
                onClick={() => {
                  setErrorMsg(null)
                  setInfoMsg('Pide a tu administrador que restablezca tu contraseña.')
                }}
                className="font-medium text-slate-950 hover:text-slate-800 hover:underline transition-colors cursor-pointer"
              >
                ¿Olvidó su contraseña?
              </button>
            </div>

            {/* Botón Principal Negro Carbón Slate-950 */}
            <div className="pt-2">
              <Button
                type="submit"
                disabled={isLoading}
                className="h-11 w-full rounded-lg bg-slate-950 hover:bg-slate-900 active:bg-black text-white font-semibold text-sm tracking-wide shadow-md shadow-slate-950/20 duration-150 ease-out motion-safe:active:scale-[0.96] transition-all cursor-pointer border-0 outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-slate-950 disabled:pointer-events-none disabled:opacity-60 disabled:active:scale-100"
              >
                {isLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <Loader2 className="h-4 w-4 animate-spin text-white" />
                    <span>Iniciando sesión...</span>
                  </span>
                ) : (
                  'Iniciar Sesión'
                )}
              </Button>
            </div>

            {/* Enlace de Soporte */}
            <div className="pt-3 text-center text-xs text-slate-500">
              ¿No tiene una cuenta?{' '}
              <button
                type="button"
                onClick={() => {
                  setErrorMsg(null)
                  setInfoMsg(
                    <span>
                      Para asistencia técnica o soporte de la plataforma, escribe a{' '}
                      <a
                        href="mailto:contacto@asescon.pe"
                        className="font-semibold text-sky-900 underline hover:text-sky-950"
                      >
                        contacto@asescon.pe
                      </a>
                    </span>
                  )
                }}
                className="font-semibold text-slate-950 hover:text-slate-800 hover:underline transition-colors cursor-pointer"
              >
                Contactar soporte
              </button>
            </div>
          </form>
        </div>

        {/* 3. Footer de la Columna Izquierda */}
        <div className="flex items-center justify-between text-xs text-slate-400 pt-6 border-t border-slate-100">
          <span>&copy; {new Date().getFullYear()} FACT-KARD Inc.</span>
          <span>Todos los derechos reservados</span>
        </div>
      </div>

      {/* Columna Derecha: Panel de portada con bordes redondeados, marco delgado y espaciado compacto */}
      <div className="hidden lg:block py-1.5 pr-1.5 lg:py-2 lg:pr-2 pl-0 h-full">
        <div className="relative h-full w-full rounded-l-none rounded-r-xl overflow-hidden border border-slate-200 bg-slate-950 shadow-xs flex flex-col justify-end p-8 sm:p-10 lg:p-12 xl:p-14">
          <img
            src="/login-cover.webp"
            alt="FACT-KARD Cover"
            className="absolute inset-0 h-full w-full object-cover object-center"
          />

          {/* Gradiente cinemático vertical integrado (sin cajas ni bordes) */}
          <div
            className="absolute inset-0 bg-gradient-to-t from-slate-950 via-slate-950/40 to-transparent pointer-events-none"
            aria-hidden="true"
          />

          {/* Tipografía editorial en la base con jerarquía impecable */}
          <div className="relative z-10 max-w-lg">
            <span className="text-[11px] font-semibold uppercase tracking-widest text-slate-400 block mb-2.5">
              Facturación Electrónica &bull; Kardex Valorizado
            </span>
            <h2 className="text-xl sm:text-2xl xl:text-3xl font-extrabold tracking-tight text-white leading-snug">
              Control tributario y Kardex con precisión milimétrica.
            </h2>
            <p className="mt-2.5 text-xs sm:text-sm text-slate-300 font-normal leading-relaxed">
              Sincronización en tiempo real entre inventarios físicos y comprobantes electrónicos SUNAT.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default LoginPage
