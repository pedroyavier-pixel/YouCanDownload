# YouCanDownload

Una interfaz sencilla: pega un enlace de YouTube y se prepara automáticamente un archivo con video y audio, en la mejor resolución que el video original ofrezca.

## Estado

**Edición Mac disponible:** abre `LEEME_MAC.md`. Incluye lanzadores para la propia Mac y para dispositivos del mismo Wi-Fi. El motor local no redirige a Render. La instalación y la descarga real en macOS están pendientes de verificación en la computadora del usuario.

**Verificación del 16 de octubre de 2026:** el servicio está desplegado en el plan gratuito de Render en https://youcandownload.onrender.com/ y GitHub Pages redirige a esa aplicación. La descarga real de prueba (`YE7VzlLtp-4`, Blender) falló porque YouTube respondió «Sign in to confirm you’re not a bot». Se repitió la verificación con yt-dlp nightly `2026.10.10.233141`, con el mismo resultado. **No se ha verificado ninguna descarga real exitosa desde este servidor; el objetivo funcional sigue pendiente.** No se han añadido cookies, proxies ni mecanismos para eludir esa verificación.

El código incluye la interfaz y el servidor de descargas. **Publicar los archivos en GitHub Pages no activa las descargas:** Pages solo sirve HTML, CSS y JavaScript. Se necesita desplegar el servidor Docker incluido. No hay una API externa pública ni descargas simuladas.

## Publicar online desde este repositorio

1. En Render, crea un **Blueprint** conectado a este repositorio y selecciona `render.yaml`. Revisa el plan antes de confirmar. El archivo propone un servicio gratuito; su disponibilidad y condiciones dependen de Render.
2. Define `APP_ACCESS_CODE` con una clave privada de acceso. No la escribas en el código ni en GitHub. También puedes omitir esta variable para una instalación sin clave; en ese caso cualquier visitante podrá consumir los recursos del servidor.
3. Render construye el Dockerfile y proporciona una dirección HTTPS. Esa dirección sirve **la aplicación completa** y funciona desde teléfono, tableta y computadora.
4. Si quieres entrar por GitHub Pages, configura **Settings → Pages → Deploy from a branch → main → /(root)**. El repositorio contiene una copia estática en la raíz. Cambia la variable `window.YCD_ENGINE_URL` en el `config.js` de la raíz a la dirección HTTPS de Render. La página de GitHub enviará al visitante a la aplicación completa. El Dockerfile sustituye esta configuración por un valor vacío al construir el servicio, para evitar redirecciones en bucle.

No requiere contratar un dominio. El nombre del producto es YouCanDownload; las direcciones disponibles dependen del proveedor.

## Ejecutar el servicio en cualquier servidor Docker

```sh
docker build -t youcandownload .
docker run --rm -p 8000:8000 --env-file .env youcandownload
```

Crea `.env` fuera de Git con `APP_ACCESS_CODE=tu-clave-privada`. Abre `http://localhost:8000`. Para acceso por internet, usa HTTPS y un proxy inverso de tu proveedor.

## Desarrollo y verificación

Requiere Python 3.12, FFmpeg/ffprobe y Node 22 o superior.

```sh
python -m pip install -r requirements-dev.txt
python -m pytest -q
uvicorn server:app --host 0.0.0.0 --port 8000 --workers 1
```

Las pruebas verifican la selección de formato, la descarga y unión real de pistas locales con FFmpeg, la presencia de video y audio con ffprobe, la validación de enlaces, el aislamiento de sesiones, la cancelación y la entrega del archivo. Esa verificación no sustituye una prueba de YouTube desde la IP del alojamiento final.

## Funcionamiento

- Reconoce enlaces de videos, Shorts y transmisiones ya terminadas. Ignora parámetros de listas para descargar solo el video indicado.
- yt-dlp elige video y audio. Se prioriza la resolución y después los FPS. No inventa 1080p si el original es menor.
- FFmpeg une las pistas sin reescalarlas ni recodificarlas. Se utiliza MP4 cuando es compatible con las pistas, o MKV como alternativa. La compatibilidad de reproducción depende de los códecs y del dispositivo.
- Cada trabajo tiene un identificador aleatorio y pertenece a la sesión que lo inició. Los archivos se borran tras una hora sin uso.
- De forma predeterminada: una descarga simultánea, hasta 1 GiB y dos horas de duración. Estos límites se pueden cambiar mediante variables de entorno según el alojamiento.
- El porcentaje mostrado corresponde a la pista que se está descargando, seguido por una fase de unión. No representa un porcentaje global ficticio.
- Al terminar se intenta iniciar la descarga. Algunos navegadores, especialmente móviles, requieren tocar **Guardar video**.

## Límites del despliegue

YouTube puede rechazar conexiones desde IPs de centros de datos, requerir autenticación o cambiar sus mecanismos. La aplicación muestra esos errores; no garantiza acceso a todos los videos. No incluye cookies de YouTube, proxies, evasión de restricciones ni acceso a videos privados. Actualiza `yt-dlp[default]` y vuelve a desplegar cuando cambie YouTube.

Los trabajos son temporales y se guardan en memoria y disco local: usa **una instancia y un worker**. Reiniciar o suspender el servicio pierde los trabajos activos. Un servicio gratuito puede suspenderse; para uso frecuente necesitarás revisar las condiciones y capacidad del proveedor.

## Variables

| Variable | Predeterminado | Uso |
|---|---|---|
| `PORT` | `8000` | Puerto HTTP |
| `APP_ACCESS_CODE` | vacío | Clave opcional; se configura en el alojamiento |
| `MAX_ACTIVE_JOBS` | `1` | Descargas simultáneas |
| `MAX_FILE_BYTES` | `1073741824` | Tamaño máximo del archivo |
| `MAX_DURATION_SECONDS` | `7200` | Duración máxima del video |
| `JOB_TIMEOUT_SECONDS` | `1800` | Tiempo máximo de procesamiento |
| `FILE_TTL_SECONDS` | `3600` | Tiempo de conservación |
| `DOWNLOAD_DIR` | `/tmp/youcandownload` | Directorio temporal exclusivo |

## Referencias técnicas

- [GitHub Pages: alojamiento estático](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)
- [yt-dlp y FFmpeg](https://github.com/yt-dlp/yt-dlp)
- [Configuración JavaScript de yt-dlp](https://github.com/yt-dlp/yt-dlp/wiki/EJS)
- [Render Blueprints](https://render.com/docs/blueprint-spec)
