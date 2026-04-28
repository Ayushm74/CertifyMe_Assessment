# Backend Setup

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Set MySQL connection details before starting Flask:

```powershell
$env:MYSQL_HOST="localhost"
$env:MYSQL_PORT="3306"
$env:MYSQL_USER="root"
$env:MYSQL_PASSWORD="root"
$env:MYSQL_DATABASE="certify_me"
$env:SECRET_KEY="mysecretkey123"
$env:ALLOWED_ORIGINS="https://certify-me-assessment-zqqv.vercel.app"
$env:SESSION_COOKIE_SAMESITE="None"
$env:SESSION_COOKIE_SECURE="true"
python app.py
```

The app creates the configured MySQL database and required tables automatically on startup:

- `admins`
- `password_reset_tokens`
- `opportunities`

Forgot-password reset links are logged in the Flask console and expire after 1 hour.

The active frontend file is `sky/index.html`; Flask serves it from `/` and serves `admin.css` / `admin.js` from the same static folder.
