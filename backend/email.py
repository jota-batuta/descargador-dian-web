"""Send transactional emails via SMTP (Gmail app password)."""

from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
_SMTP_USER = os.getenv("SMTP_USER", "")
_SMTP_PASS = os.getenv("SMTP_PASS", "")
_FROM_NAME = "Dian Downloader Batuta"


def _send_sync(to: str, subject: str, html: str) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{_FROM_NAME} <{_SMTP_USER}>"
    msg["To"] = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as s:
        s.ehlo()
        s.starttls(context=ctx)
        s.login(_SMTP_USER, _SMTP_PASS)
        s.sendmail(_SMTP_USER, to, msg.as_bytes())


async def send_welcome(to: str, full_name: str, trial_days: int = 120) -> None:
    html = f"""
<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"></head>
<body style="font-family:'Segoe UI',sans-serif;background:#f0f2f5;padding:32px">
  <div style="max-width:520px;margin:0 auto;background:#fff;border-radius:12px;
              box-shadow:0 4px 16px rgba(0,0,0,.08);overflow:hidden">
    <div style="background:#E94560;padding:28px 36px">
      <h1 style="color:#fff;margin:0;font-size:1.4rem;font-weight:700">
        Dian Downloader Batuta
      </h1>
    </div>
    <div style="padding:32px 36px">
      <p style="font-size:1rem;color:#111;margin-bottom:16px">
        Hola <strong>{full_name}</strong>,
      </p>
      <p style="color:#444;line-height:1.6">
        Tu cuenta ha sido creada con éxito. Tienes acceso completo durante
        <strong>{trial_days} días</strong> desde hoy.
      </p>
      <p style="color:#444;line-height:1.6;margin-top:16px">
        Para descargar tus documentos DIAN:
      </p>
      <ol style="color:#444;line-height:1.8;padding-left:20px">
        <li>Inicia sesión en el portal DIAN y copia tu token URL.</li>
        <li>Pégalo en la app junto con el rango de fechas.</li>
        <li>Espera la descarga y guarda tu ZIP.</li>
      </ol>
      <div style="text-align:center;margin-top:28px">
        <a href="https://descargasdian.batutaai.com"
           style="background:#E94560;color:#fff;text-decoration:none;
                  padding:12px 32px;border-radius:8px;font-weight:700;font-size:1rem">
          Ir a la app
        </a>
      </div>
      <p style="color:#888;font-size:.82rem;margin-top:28px;border-top:1px solid #f0f2f5;padding-top:16px">
        Batuta AI SAS · www.batutaai.com<br>
        Este correo fue enviado automáticamente, no respondas a este mensaje.
      </p>
    </div>
  </div>
</body>
</html>
"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _send_sync(to, "Bienvenido a Dian Downloader Batuta", html),
    )


async def send_welcome_background(to: str, full_name: str) -> None:
    """Fire-and-forget: log error but never raise, so registration still succeeds."""
    try:
        await send_welcome(to, full_name)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Email send failed to %s: %s", to, exc)
