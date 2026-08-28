import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

const backendTarget = process.env.VITE_BACKEND_TARGET || (process.env.NODE_ENV === 'production' ? 'http://backend:8000' : 'http://localhost:8002')

export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src'),
            '@material-tailwind/react': path.resolve(__dirname, './node_modules/@material-tailwind/react'),
        },
    },
    optimizeDeps: {
        include: ['@apollo/client'],
    },
    server: {
        host: '0.0.0.0',
        port: 3000,
        proxy: {
            '/graphql': {
                target: backendTarget,
                changeOrigin: true,
                secure: false,
            },
            '/api-login/': {
                target: backendTarget,
                changeOrigin: true,
                secure: false,
            },
            '/api': {
                target: backendTarget,
                changeOrigin: true,
                secure: false,
            },
        },
    },
})
