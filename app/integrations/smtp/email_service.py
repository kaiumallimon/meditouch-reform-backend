import smtplib
import ssl
import asyncio
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Optional, Tuple
from app.core.config import settings
from app.core.logging import logger

def render_doctor_welcome_email(
    name: str,
    phone: str,
    email: str,
    passphrase: str,
    login_url: Optional[str] = None
) -> Tuple[str, str]:
    """
    Renders both Plain Text and HTML versions of the Doctor Welcome & Credentials email.
    Uses MediTouch cream UI neo-card design system.
    """
    app_url = login_url or f"{settings.FRONTEND_BASE_URL}/login"

    # 1. Plain Text Fallback (High deliverability & spam filter compliance)
    plain_text = f"""
Welcome to MediTouch Telemedicine Network
==========================================

Dear Dr. {name},

Your practitioner account has been created on the MediTouch Telemedicine platform.
Below are your secure login credentials to access your doctor workspace:

--------------------------------------------------
Login ID (Phone): {phone}
Registered Email: {email}
Generated Passphrase: {passphrase}
--------------------------------------------------

Portal Sign In URL:
{app_url}

For security, we recommend changing your password after your first login.
If you did not expect this email, please contact support@meditouch.com immediately.

Warm regards,
The MediTouch Healthcare Team
Rural & Underserved Telemedicine Network
    """.strip()

    # 2. Responsive HTML Email (Matching website cream & neo-border aesthetic)
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your MediTouch Doctor Credentials</title>
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #F7F4EE;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      color: #1C1917;
      line-height: 1.5;
    }}
    .wrapper {{
      width: 100%;
      background-color: #F7F4EE;
      padding: 40px 15px;
    }}
    .card {{
      max-width: 540px;
      margin: 0 auto;
      background-color: #FFFFFF;
      border: 2px solid #1C1917;
      border-radius: 18px;
      box-shadow: 4px 4px 0px 0px #1C1917;
      padding: 36px 32px;
    }}
    .header-pill {{
      display: inline-block;
      background-color: #EDE8FE;
      color: #5B15FC;
      border: 1px solid #5B15FC;
      border-radius: 100px;
      padding: 4px 12px;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      margin-bottom: 16px;
    }}
    .title {{
      font-family: 'Young Serif', Georgia, serif;
      font-size: 24px;
      font-weight: 400;
      color: #1C1917;
      margin: 0 0 8px 0;
      line-height: 1.25;
    }}
    .subtitle {{
      font-size: 13px;
      color: #78716C;
      margin: 0 0 24px 0;
    }}
    .credential-box {{
      background-color: #FAF8F5;
      border: 1.5px solid #1C1917;
      border-radius: 14px;
      padding: 20px;
      margin: 24px 0;
    }}
    .cred-row {{
      margin-bottom: 12px;
    }}
    .cred-row:last-child {{
      margin-bottom: 0;
    }}
    .cred-label {{
      font-size: 10px;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.75px;
      color: #78716C;
      margin-bottom: 4px;
    }}
    .cred-value {{
      font-size: 14px;
      font-weight: 600;
      color: #1C1917;
    }}
    .passphrase-highlight {{
      font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace;
      font-size: 16px;
      font-weight: 700;
      color: #5B15FC;
      background-color: #FFFFFF;
      border: 1.5px solid #1C1917;
      border-radius: 8px;
      padding: 10px 14px;
      letter-spacing: 1px;
      margin-top: 4px;
      display: block;
      box-shadow: 2px 2px 0px 0px #1C1917;
    }}
    .button {{
      display: block;
      width: 100%;
      text-align: center;
      background-color: #5B15FC;
      color: #FFFFFF !important;
      font-size: 13px;
      font-weight: 700;
      text-decoration: none;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      padding: 14px 20px;
      border-radius: 12px;
      border: 1.5px solid #1C1917;
      box-shadow: 3px 3px 0px 0px #1C1917;
      box-sizing: border-box;
      margin: 28px 0 20px 0;
    }}
    .footer-note {{
      font-size: 11px;
      color: #A8A29E;
      line-height: 1.4;
      text-align: center;
      border-top: 1px solid #E7E5E4;
      padding-top: 20px;
      margin-top: 24px;
    }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <span class="header-pill">Practitioner Credentials</span>
      <h1 class="title">Welcome to MediTouch</h1>
      <p class="subtitle">Your practitioner profile is registered on our Telemedicine network.</p>

      <p style="font-size: 13px; color: #44403C; margin: 0 0 16px 0;">
        Dear <strong>Dr. {name}</strong>,<br>
        An administrative account has been set up for you. Use the secure login details below to access your consultation dashboard:
      </p>

      <div class="credential-box">
        <div class="cred-row">
          <div class="cred-label">Login Identifier (Phone)</div>
          <div class="cred-value">{phone}</div>
        </div>
        <div class="cred-row">
          <div class="cred-label">Registered Email</div>
          <div class="cred-value">{email}</div>
        </div>
        <div class="cred-row" style="margin-top: 16px;">
          <div class="cred-label">Temporary Passphrase</div>
          <div class="passphrase-highlight">{passphrase}</div>
        </div>
      </div>

      <a href="{app_url}" class="button" target="_blank">
        Sign in to Doctor Workspace &rarr;
      </a>

      <p style="font-size: 11px; color: #78716C; margin: 12px 0 0 0; text-align: center;">
        &#128274; For security, please change your password after your initial login.
      </p>

      <div class="footer-note">
        MediTouch Healthcare Bangladesh &bull; Rural & Underserved Telemedicine Platform<br>
        Need assistance? Contact support at <a href="mailto:support@meditouch.com" style="color: #5B15FC; text-decoration: none;">support@meditouch.com</a>
      </div>
    </div>
  </div>
</body>
</html>
    """.strip()

    return plain_text, html_content


class EmailService:
    @staticmethod
    def _send_sync(msg: MIMEMultipart, to_email: str) -> bool:
        """Synchronous SMTP worker executed in thread pool."""
        try:
            if settings.SMTP_SSL:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context, timeout=15) as server:
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                    server.ehlo()
                    if settings.SMTP_TLS:
                        context = ssl.create_default_context()
                        server.starttls(context=context)
                        server.ehlo()
                    if settings.SMTP_USER and settings.SMTP_PASSWORD:
                        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                    server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            return True
        except Exception as exc:
            logger.error(f"Failed to send email via SMTP to {to_email}: {exc}", exc_info=True)
            return False

    @classmethod
    async def send_doctor_welcome_email(
        cls,
        name: str,
        phone: str,
        email: str,
        passphrase: str,
        login_url: Optional[str] = None
    ) -> bool:
        """
        Dispatches the welcome credentials email to a newly created doctor.
        If SMTP is not configured in development, logs the email payload and passphrase cleanly.
        """
        plain_text, html_content = render_doctor_welcome_email(
            name=name,
            phone=phone,
            email=email,
            passphrase=passphrase,
            login_url=login_url
        )

        subject = "Your MediTouch Doctor Portal Credentials"
        from_header = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        to_header = f"Dr. {name} <{email}>"

        # Check if SMTP credentials are provided
        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info("=" * 70)
            logger.info(f"[DEV MODE / MOCK EMAIL DISPATCHED]")
            logger.info(f"To: {to_header}")
            logger.info(f"Subject: {subject}")
            logger.info(f"Login ID (Phone): {phone}")
            logger.info(f"Generated Passphrase: {passphrase}")
            logger.info(f"Portal URL: {login_url or f'{settings.FRONTEND_BASE_URL}/login'}")
            logger.info("=" * 70)
            return True

        # Build RFC compliant MIME message with anti-spam headers
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to_header
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="meditouch.com")
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Mailer"] = "MediTouch Telemedicine Engine v1.0"
        msg["List-Unsubscribe"] = "<mailto:support@meditouch.com?subject=unsubscribe>"

        # Attach text and html parts (alternative)
        part1 = MIMEText(plain_text, "plain", "utf-8")
        part2 = MIMEText(html_content, "html", "utf-8")
        msg.attach(part1)
        msg.attach(part2)

        # Send asynchronously via thread pool
        success = await asyncio.to_thread(cls._send_sync, msg, email)
        return success

    @classmethod
    async def send_user_welcome_email(
        cls,
        name: str,
        phone: str,
        email: str,
        passphrase: str,
        role: str = "ADMIN",
        login_url: Optional[str] = None
    ) -> bool:
        """
        Dispatches credentials email to a newly created Admin, Nurse, Doctor, or Patient account.
        """
        app_url = login_url or f"{settings.FRONTEND_BASE_URL}/login"
        role_label = role.capitalize()

        plain_text = f"""
Welcome to MediTouch Healthcare Platform
=========================================

Dear {name},

Your {role_label} account has been created on MediTouch.
Below are your secure login credentials to access the platform:

--------------------------------------------------
Login ID (Phone): {phone}
Registered Email: {email}
Role: {role_label}
Generated Passphrase: {passphrase}
--------------------------------------------------

Sign In Portal URL:
{app_url}

For security, please change your password after logging in.
If you did not expect this email, contact support@meditouch.com immediately.

Warm regards,
The MediTouch Healthcare Team
        """.strip()

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Your MediTouch {role_label} Account Credentials</title>
  <style>
    body {{ margin: 0; padding: 0; background-color: #F7F4EE; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1C1917; }}
    .wrapper {{ width: 100%; background-color: #F7F4EE; padding: 40px 15px; }}
    .card {{ max-width: 540px; margin: 0 auto; background-color: #FFFFFF; border: 2px solid #1C1917; border-radius: 18px; box-shadow: 4px 4px 0px 0px #1C1917; padding: 36px 32px; }}
    .header-pill {{ display: inline-block; background-color: #EDE8FE; color: #5B15FC; border: 1px solid #5B15FC; border-radius: 100px; padding: 4px 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 16px; }}
    .title {{ font-family: 'Young Serif', Georgia, serif; font-size: 24px; font-weight: 400; color: #1C1917; margin: 0 0 8px 0; }}
    .subtitle {{ font-size: 13px; color: #78716C; margin: 0 0 24px 0; }}
    .credential-box {{ background-color: #FAF8F5; border: 1.5px solid #1C1917; border-radius: 14px; padding: 20px; margin: 24px 0; }}
    .cred-row {{ margin-bottom: 12px; }}
    .cred-row:last-child {{ margin-bottom: 0; }}
    .cred-label {{ font-size: 10px; font-weight: 700; text-transform: uppercase; color: #78716C; margin-bottom: 4px; }}
    .cred-value {{ font-size: 14px; font-weight: 600; color: #1C1917; }}
    .passphrase-highlight {{ font-family: monospace; font-size: 16px; font-weight: 700; color: #5B15FC; background-color: #FFFFFF; border: 1.5px solid #1C1917; border-radius: 8px; padding: 10px 14px; display: block; box-shadow: 2px 2px 0px 0px #1C1917; margin-top: 4px; }}
    .button {{ display: block; width: 100%; text-align: center; background-color: #5B15FC; color: #FFFFFF !important; font-size: 13px; font-weight: 700; text-decoration: none; text-transform: uppercase; padding: 14px 20px; border-radius: 12px; border: 1.5px solid #1C1917; box-shadow: 3px 3px 0px 0px #1C1917; box-sizing: border-box; margin: 28px 0 20px 0; }}
    .footer-note {{ font-size: 11px; color: #A8A29E; text-align: center; border-top: 1px solid #E7E5E4; padding-top: 20px; margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <span class="header-pill">{role_label} Account</span>
      <h1 class="title">Welcome to MediTouch</h1>
      <p class="subtitle">An official {role_label} profile has been created for you.</p>
      <p style="font-size: 13px; color: #44403C; margin: 0 0 16px 0;">
        Dear <strong>{name}</strong>,<br>
        Your credentials have been provisioned by the platform administrator. Sign in below:
      </p>
      <div class="credential-box">
        <div class="cred-row"><div class="cred-label">Login ID (Phone)</div><div class="cred-value">{phone}</div></div>
        <div class="cred-row"><div class="cred-label">Registered Email</div><div class="cred-value">{email}</div></div>
        <div class="cred-row"><div class="cred-label">Account Role</div><div class="cred-value">{role_label}</div></div>
        <div class="cred-row" style="margin-top: 16px;"><div class="cred-label">Generated Passphrase</div><div class="passphrase-highlight">{passphrase}</div></div>
      </div>
      <a href="{app_url}" class="button" target="_blank">Access Portal &rarr;</a>
      <p style="font-size: 11px; color: #78716C; text-align: center; margin-top: 12px;">&#128274; For security, please change your password after initial sign in.</p>
      <div class="footer-note">MediTouch Healthcare &bull; Support: <a href="mailto:support@meditouch.com" style="color: #5B15FC;">support@meditouch.com</a></div>
    </div>
  </div>
</body>
</html>
        """.strip()

        subject = f"Your MediTouch {role_label} Account Credentials"
        from_header = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        to_header = f"{name} <{email}>"

        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info("=" * 70)
            logger.info(f"[DEV MODE / MOCK USER EMAIL]")
            logger.info(f"To: {to_header} | Role: {role_label}")
            logger.info(f"Phone: {phone} | Passphrase: {passphrase}")
            logger.info("=" * 70)
            return True

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to_header
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="meditouch.com")
        msg["Auto-Submitted"] = "auto-generated"
        msg["X-Mailer"] = "MediTouch System Engine"

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        return await asyncio.to_thread(cls._send_sync, msg, email)

    @classmethod
    async def send_password_recovery_email(
        cls,
        name: str,
        phone: str,
        email: str,
        passphrase: str,
        role: str = "USER",
        login_url: Optional[str] = None
    ) -> bool:
        """
        Dispatches password reset / recovery email with a fresh secure passphrase.
        """
        app_url = login_url or f"{settings.FRONTEND_BASE_URL}/login"
        role_label = role.capitalize()

        plain_text = f"""
Password Recovery - MediTouch Healthcare
=========================================

Dear {name},

An administrator has initiated a password recovery request for your {role_label} account.
Your new login passphrase is:

--------------------------------------------------
Login ID (Phone): {phone}
Registered Email: {email}
Temporary Passphrase: {passphrase}
--------------------------------------------------

Login URL:
{app_url}

Please use this passphrase to sign in and immediately update your password.
If you did not request this, please contact support@meditouch.com immediately.

Warm regards,
The MediTouch Healthcare Team
        """.strip()

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Password Recovery - MediTouch</title>
  <style>
    body {{ margin: 0; padding: 0; background-color: #F7F4EE; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; color: #1C1917; }}
    .wrapper {{ width: 100%; background-color: #F7F4EE; padding: 40px 15px; }}
    .card {{ max-width: 540px; margin: 0 auto; background-color: #FFFFFF; border: 2px solid #1C1917; border-radius: 18px; box-shadow: 4px 4px 0px 0px #1C1917; padding: 36px 32px; }}
    .header-pill {{ display: inline-block; background-color: #FEE2E2; color: #DC2626; border: 1px solid #DC2626; border-radius: 100px; padding: 4px 12px; font-size: 11px; font-weight: 700; text-transform: uppercase; margin-bottom: 16px; }}
    .title {{ font-family: 'Young Serif', Georgia, serif; font-size: 24px; font-weight: 400; color: #1C1917; margin: 0 0 8px 0; }}
    .subtitle {{ font-size: 13px; color: #78716C; margin: 0 0 24px 0; }}
    .credential-box {{ background-color: #FAF8F5; border: 1.5px solid #1C1917; border-radius: 14px; padding: 20px; margin: 24px 0; }}
    .cred-row {{ margin-bottom: 12px; }}
    .cred-row:last-child {{ margin-bottom: 0; }}
    .cred-label {{ font-size: 10px; font-weight: 700; text-transform: uppercase; color: #78716C; margin-bottom: 4px; }}
    .cred-value {{ font-size: 14px; font-weight: 600; color: #1C1917; }}
    .passphrase-highlight {{ font-family: monospace; font-size: 16px; font-weight: 700; color: #5B15FC; background-color: #FFFFFF; border: 1.5px solid #1C1917; border-radius: 8px; padding: 10px 14px; display: block; box-shadow: 2px 2px 0px 0px #1C1917; margin-top: 4px; }}
    .button {{ display: block; width: 100%; text-align: center; background-color: #5B15FC; color: #FFFFFF !important; font-size: 13px; font-weight: 700; text-decoration: none; text-transform: uppercase; padding: 14px 20px; border-radius: 12px; border: 1.5px solid #1C1917; box-shadow: 3px 3px 0px 0px #1C1917; box-sizing: border-box; margin: 28px 0 20px 0; }}
    .footer-note {{ font-size: 11px; color: #A8A29E; text-align: center; border-top: 1px solid #E7E5E4; padding-top: 20px; margin-top: 24px; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <span class="header-pill">Security &bull; Password Reset</span>
      <h1 class="title">Password Recovery</h1>
      <p class="subtitle">Your MediTouch {role_label} account passphrase has been regenerated.</p>
      <p style="font-size: 13px; color: #44403C; margin: 0 0 16px 0;">
        Dear <strong>{name}</strong>,<br>
        An administrator has issued a new secure passphrase for your account:
      </p>
      <div class="credential-box">
        <div class="cred-row"><div class="cred-label">Login Identifier (Phone)</div><div class="cred-value">{phone}</div></div>
        <div class="cred-row"><div class="cred-label">Registered Email</div><div class="cred-value">{email}</div></div>
        <div class="cred-row" style="margin-top: 16px;"><div class="cred-label">New Temporary Passphrase</div><div class="passphrase-highlight">{passphrase}</div></div>
      </div>
      <a href="{app_url}" class="button" target="_blank">Sign in to Account &rarr;</a>
      <p style="font-size: 11px; color: #78716C; text-align: center; margin-top: 12px;">&#128274; Please change this temporary passphrase immediately after signing in.</p>
      <div class="footer-note">MediTouch Healthcare Security &bull; Questions? Contact <a href="mailto:support@meditouch.com" style="color: #5B15FC;">support@meditouch.com</a></div>
    </div>
  </div>
</body>
</html>
        """.strip()

        subject = "MediTouch Account Password Recovery"
        from_header = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        to_header = f"{name} <{email}>"

        if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
            logger.info("=" * 70)
            logger.info(f"[DEV MODE / PASSWORD RECOVERY EMAIL]")
            logger.info(f"To: {to_header} | Phone: {phone}")
            logger.info(f"New Passphrase: {passphrase}")
            logger.info("=" * 70)
            return True

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_header
        msg["To"] = to_header
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain="meditouch.com")
        msg["Auto-Submitted"] = "auto-generated"

        msg.attach(MIMEText(plain_text, "plain", "utf-8"))
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        return await asyncio.to_thread(cls._send_sync, msg, email)

