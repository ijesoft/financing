import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vitejs.dev/config/
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
                target: 'http://localhost:8002',
                changeOrigin: true,
                secure: false,
            },
            '/api-login/': {
                target: 'http://localhost:8002',
                changeOrigin: true,
                secure: false,
            },
            '/api': {
                target: 'http://localhost:8002',
                changeOrigin: true,
                secure: false,
            },
        },
    },
})
