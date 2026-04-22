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
_FROM_NAME = "Batuta AI"
_APP_URL = os.getenv("APP_PUBLIC_URL", "https://descargasdian.batutaai.com")
_SITE_URL = "https://www.batutaai.com"
# Absolute asset URLs — Gmail strips inline SVG and <style>, so we use PNG + inline attributes.
_LOGO_URL = f"{_APP_URL}/static/logo.png"


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


def _render_welcome_html(full_name: str, trial_days: int) -> str:
    """Render the welcome email with Batuta AI identity.

    Uses inline styles + table layout for Gmail/Outlook compatibility.
    Palette: nocturno #0E1220 · noche-profunda #161B2E · bruma-clara #ECEFF6
    · bruma #A8B0C2 · cobalto #4D5CFF · grafito #262B3D.
    """
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Bienvenido a Batuta AI</title>
</head>
<body style="margin:0;padding:0;background:#0E1220;font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#ECEFF6;">
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
         style="background:#0E1220;padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="560"
               style="max-width:560px;background:#161B2E;border:1px solid #262B3D;border-radius:12px;overflow:hidden;">

          <!-- Header with logo -->
          <tr>
            <td style="padding:28px 36px 20px;border-bottom:1px solid #262B3D;">
              <a href="{_SITE_URL}" target="_blank" rel="noopener"
                 style="text-decoration:none;display:inline-block;">
                <table role="presentation" cellpadding="0" cellspacing="0" border="0">
                  <tr>
                    <td style="padding-right:10px;vertical-align:middle;">
                      <img src="{_LOGO_URL}" alt="Batuta AI" width="32" height="32"
                           style="display:block;border:0;outline:none;text-decoration:none;width:32px;height:32px;">
                    </td>
                    <td style="vertical-align:middle;">
                      <span style="font-family:'Inter',Arial,sans-serif;font-size:18px;font-weight:700;color:#ECEFF6;letter-spacing:-0.01em;">
                        Batuta <span style="color:#4D5CFF;">AI</span>
                      </span>
                    </td>
                  </tr>
                </table>
              </a>
            </td>
          </tr>

          <!-- Body -->
          <tr>
            <td style="padding:32px 36px 8px;">
              <p style="margin:0 0 6px;font-size:12px;font-weight:600;color:#4D5CFF;text-transform:uppercase;letter-spacing:0.08em;font-family:'Inter',Arial,sans-serif;">
                DIAN Downloader
              </p>
              <h1 style="margin:0 0 18px;font-size:22px;font-weight:700;color:#ECEFF6;line-height:1.3;letter-spacing:-0.01em;font-family:'Inter',Arial,sans-serif;">
                Bienvenido, {full_name}
              </h1>
              <p style="margin:0 0 14px;font-size:15px;color:#A8B0C2;line-height:1.6;font-family:'Inter',Arial,sans-serif;">
                Tu cuenta ya está activa. Tienes acceso completo al DIAN Downloader durante
                <strong style="color:#ECEFF6;">{trial_days} días</strong> desde hoy.
              </p>
              <p style="margin:0 0 10px;font-size:15px;color:#A8B0C2;line-height:1.6;font-family:'Inter',Arial,sans-serif;">
                Para descargar tus documentos DIAN:
              </p>
              <ol style="margin:0 0 24px;padding-left:20px;font-size:14px;color:#A8B0C2;line-height:1.8;font-family:'Inter',Arial,sans-serif;">
                <li>Inicia sesión en el portal DIAN y copia tu token URL.</li>
                <li>Pégalo en la app junto con el rango de fechas.</li>
                <li>Espera la descarga y guarda tu ZIP.</li>
              </ol>

              <!-- CTA -->
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr>
                  <td align="center" style="padding:4px 0 28px;">
                    <a href="{_APP_URL}" target="_blank" rel="noopener"
                       style="display:inline-block;background:#4D5CFF;color:#ffffff;text-decoration:none;padding:13px 34px;border-radius:8px;font-weight:700;font-size:15px;font-family:'Inter',Arial,sans-serif;letter-spacing:0.01em;">
                      Ir a la app
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Footer -->
          <tr>
            <td style="padding:20px 36px 28px;border-top:1px solid #262B3D;">
              <p style="margin:0 0 6px;font-size:12px;color:#6B7593;line-height:1.6;font-family:'Inter',Arial,sans-serif;">
                Batuta AI SAS · <a href="{_SITE_URL}" style="color:#4D5CFF;text-decoration:none;">www.batutaai.com</a>
              </p>
              <p style="margin:0;font-size:12px;color:#6B7593;line-height:1.6;font-family:'Inter',Arial,sans-serif;">
                Este correo fue enviado automáticamente. Si no reconoces esta cuenta, ignora este mensaje.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


async def send_welcome(to: str, full_name: str, trial_days: int = 120) -> None:
    html = _render_welcome_html(full_name, trial_days)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: _send_sync(to, "Bienvenido a Batuta AI — DIAN Downloader", html),
    )


async def send_welcome_background(to: str, full_name: str) -> None:
    """Fire-and-forget: log error but never raise, so registration still succeeds."""
    try:
        await send_welcome(to, full_name)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning("Email send failed to %s: %s", to, exc)
