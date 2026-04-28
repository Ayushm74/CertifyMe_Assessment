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
python app.py
```

The app creates the configured MySQL database and required tables automatically on startup:

- `admins`
- `password_reset_tokens`
- `opportunities`

Forgot-password reset links are logged in the Flask console and expire after 1 hour.
