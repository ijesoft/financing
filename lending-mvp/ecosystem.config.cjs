module.exports = {
  apps: [
    {
      name: 'lending-frontend',
      cwd: '/home/ubuntu/Github/financing/lending-mvp/frontend-react',
      script: '/home/ubuntu/.nvm/versions/node/v22.22.0/bin/serve',
      args: '-s dist -l 8810 --no-clipboard',
      interpreter: 'none',
      env: {
        NODE_ENV: 'production',
      },
    },
    {
      name: 'lending-backend',
      cwd: '/home/ubuntu/Github/financing/lending-mvp/backend',
      script: 'uvicorn',
      args: 'app.main:app --host 0.0.0.0 --port 8811',
      interpreter: 'none',
      env: {
        PYTHONPATH: '/home/ubuntu/Github/financing/lending-mvp/backend',
        SEED_DEMO_DATA: 'true',
        LOG_LEVEL: 'INFO',
        BUSINESS_COUNTRY: 'Philippines',
        CURRENCY: 'PHP',
        TIMEZONE: 'Asia/Manila',
      },
      env_file: '/home/ubuntu/Github/financing/lending-mvp/backend/.env',
    },
  ],
}
