import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import { isEmbedded } from './integration'
import './styles/tokens.css'
import './styles/app.css'

if (!isEmbedded && 'serviceWorker' in navigator && import.meta.env.PROD) navigator.serviceWorker.register('/sw.js')

ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
