import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { CaptureModeProvider } from '@/components/CaptureModeProvider'
import { SessionProvider } from '@/components/SessionProvider'
import { SetupModeProvider } from '@/components/SetupModeProvider'
import { ThemeProvider } from '@/components/ThemeProvider'
import { UnitsProvider } from '@/components/UnitsProvider'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ThemeProvider>
      <UnitsProvider>
        <SetupModeProvider>
          <CaptureModeProvider>
            <SessionProvider>
              <App />
            </SessionProvider>
          </CaptureModeProvider>
        </SetupModeProvider>
      </UnitsProvider>
    </ThemeProvider>
  </StrictMode>,
)
