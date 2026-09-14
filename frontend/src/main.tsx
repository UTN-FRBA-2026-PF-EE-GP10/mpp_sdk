import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <UnitsProvider>
        <CaptureModeProvider>
          <App />
        </CaptureModeProvider>
      </UnitsProvider>
    </ThemeProvider>
  </StrictMode>,
)
