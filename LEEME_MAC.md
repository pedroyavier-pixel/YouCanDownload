# YouCanDownload para Mac

## Arrancar

1. Descomprime `YouCanDownload-Mac.zip` y conserva toda la carpeta junta.
2. Haz doble clic en **Abrir_YouCanDownload.command**.
3. La primera vez se preparan los componentes gratuitos; después se abre la página en tu navegador.
4. Pega el enlace de YouTube. El motor intentará descargar la mejor resolución disponible y unir el audio en un solo archivo.

La versión local abre `http://127.0.0.1:8765/` (o el siguiente puerto disponible). **No te envía a Render.** No usa tu contraseña de Google ni lee cookies del navegador.

### Si aún no tienes Homebrew

El lanzador te mostrará el aviso y abrirá https://brew.sh, su página oficial. Instala Homebrew una vez siguiendo esa página y vuelve a abrir el lanzador. Si macOS pide las herramientas de desarrollo de Apple, completa su instalación. Los componentes que instalará el lanzador son Python 3.12, FFmpeg y Node 22, más las dependencias Python del proyecto.

Si macOS no permite abrir el archivo, revisa el aviso que muestra y abre el archivo desde Finder con clic secundario → Abrir cuando macOS ofrezca esa opción. Si el único problema es el permiso de ejecución, abre Terminal en esta carpeta y ejecuta:

```sh
/bin/bash ./start-mac.sh
```

No se desactiva Gatekeeper ni se modifica la configuración de seguridad de macOS.

## Usarla desde el celular o la tableta

1. Conecta la Mac y el otro dispositivo a la misma red Wi-Fi.
2. Abre **Compartir_en_WiFi.command** en la Mac.
3. La ventana de Terminal mostrará la dirección local que debes abrir en el otro dispositivo, por ejemplo `http://192.168.1.20:8765/`. Usa la dirección real mostrada por tu Mac.
4. Si el firewall de macOS solicita permitir conexiones para Python, permite el acceso únicamente si quieres compartirla en esa red.

Mantén la Mac encendida, despierta y con Terminal abierto. Una red de invitados o con aislamiento entre dispositivos puede impedir la conexión.

Esto da acceso en tu red local. **El acceso desde internet fuera de casa no está configurado.** No necesitas abrir puertos en el router para esta versión.

## Detener y volver a abrir

Pulsa **Control + C** en la ventana de Terminal que ejecuta el servidor. Para volver a usarla, abre el lanzador otra vez. Si necesitas pasar de uso exclusivo en la Mac a compartir por Wi-Fi, puedes detener primero la instancia anterior.

Los archivos preparados permanecen temporalmente en `~/Library/Application Support/YouCanDownload/temporary`, con limpieza automática. Usa «Guardar video» en el navegador para conservar la descarga. Reiniciar el motor elimina los trabajos temporales anteriores.

## Qué está comprobado

Se han verificado la selección de 1080p, transferencia de pistas de prueba, unión real con FFmpeg, presencia de video y audio, aislamiento por sesión y el modo local que evita la redirección a Render. El paquete se preparó fuera de macOS: **todavía hay que comprobar el primer arranque y una descarga real en tu Mac**. Usar tu conexión no garantiza que YouTube permita todos los videos.

El alojamiento de Render rechazó la prueba por la verificación contra bots de YouTube. Esta edición no añade proxies, cookies de cuenta ni mecanismos para eludir verificaciones. No se ha contratado ningún servicio de pago.
