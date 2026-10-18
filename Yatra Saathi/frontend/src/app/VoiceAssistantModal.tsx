import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, Check, Mic, MicOff, Send, Volume2, VolumeX, X } from 'lucide-react'
import { phase6Service } from '../services/phase6Service'
import type { StructuredVoiceAction } from '../types/travel'

interface VoiceAssistantModalProps {
  isOpen: boolean
  onClose: () => void
  currentLanguage: string
  onExecuteAction: (text: string, action?: StructuredVoiceAction | null) => void
}

export default function VoiceAssistantModal({
  isOpen,
  onClose,
  currentLanguage,
  onExecuteAction,
}: VoiceAssistantModalProps) {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [processing, setProcessing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [manualText, setManualText] = useState('')
  const [pendingConfirmation, setPendingConfirmation] = useState<{
    prompt: string
    action: StructuredVoiceAction | null
    transcript: string
  } | null>(null)
  const [isSpeaking, setIsSpeaking] = useState(false)

  const recognitionRef = useRef<any>(null)

  useEffect(() => {
    if (!isOpen) {
      stopListening()
      setTranscript('')
      setError(null)
      setPendingConfirmation(null)
      stopSpeaking()
    }
  }, [isOpen])

  function stopSpeaking() {
    if ('speechSynthesis' in window) {
      window.speechSynthesis.cancel()
      setIsSpeaking(false)
    }
  }

  function speakText(text: string, lang = currentLanguage) {
    if (!('speechSynthesis' in window)) return
    stopSpeaking()
    const utterance = new SpeechSynthesisUtterance(text)
    utterance.lang = lang
    utterance.onend = () => setIsSpeaking(false)
    utterance.onerror = () => setIsSpeaking(false)
    setIsSpeaking(true)
    window.speechSynthesis.speak(utterance)
  }

  function startListening() {
    setError(null)
    setTranscript('')
    setPendingConfirmation(null)

    const SpeechRecognition =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition

    if (!SpeechRecognition) {
      setError('Browser speech recognition is not supported in this browser. Please use the text fallback below.')
      return
    }

    try {
      const recognition = new SpeechRecognition()
      recognition.continuous = false
      recognition.interimResults = true
      recognition.lang = currentLanguage

      recognition.onstart = () => {
        setIsListening(true)
      }

      recognition.onresult = (event: any) => {
        let finalTranscript = ''
        for (let i = event.resultIndex; i < event.results.length; ++i) {
          if (event.results[i].isFinal) {
            finalTranscript += event.results[i][0].transcript
          } else {
            finalTranscript += event.results[i][0].transcript
          }
        }
        if (finalTranscript) {
          setTranscript(finalTranscript)
        }
      }

      recognition.onerror = (event: any) => {
        setIsListening(false)
        if (event.error !== 'no-speech') {
          setError(`Speech recognition notice: ${event.error}. You can use the text fallback below.`)
        }
      }

      recognition.onend = () => {
        setIsListening(false)
      }

      recognitionRef.current = recognition
      recognition.start()
    } catch (err: any) {
      setIsListening(false)
      setError('Microphone access was denied or is unavailable. Please use the text fallback below.')
    }
  }

  function stopListening() {
    if (recognitionRef.current) {
      try {
        recognitionRef.current.stop()
      } catch {
        // ignore
      }
      recognitionRef.current = null
    }
    setIsListening(false)
  }

  async function handleSendTranscript(inputPhrase: string) {
    const textToProcess = inputPhrase.trim()
    if (!textToProcess) return

    setProcessing(true)
    setError(null)

    try {
      // Backend validates via Voice API boundary
      const res = await phase6Service.transcribeAudio({
        text_hint: textToProcess,
      })

      // Section 14: Voice Confirmation Safety
      const isMaterial = Boolean(res.requires_explicit_confirmation || (res as any).pending_confirmation)
      if (isMaterial) {
        const prompt = res.confirmation_prompt || (res as any).pending_confirmation?.message || 'This action requires explicit user confirmation before proceeding.'
        setPendingConfirmation({
          prompt,
          action: (res as any).structured_action || null,
          transcript: textToProcess,
        })
        speakText(prompt)
      } else {
        // Safe query / informational action
        onExecuteAction(textToProcess, res.structured_action)
        onClose()
      }
    } catch (err: any) {
      setError(err?.message || 'Could not process voice request.')
    } finally {
      setProcessing(false)
    }
  }

  function handleConfirmMaterialAction() {
    if (!pendingConfirmation) return
    onExecuteAction(pendingConfirmation.transcript, pendingConfirmation.action)
    setPendingConfirmation(null)
    onClose()
  }

  function handleRejectMaterialAction() {
    setPendingConfirmation(null)
    setError('Material action was cancelled by user.')
  }

  if (!isOpen) return null

  return (
    <div
      className="modal-backdrop voice-modal-backdrop"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <section
        className="confirm-modal voice-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="voice-modal-title"
      >
        <button className="modal-close" aria-label="Close voice assistant" onClick={onClose}>
          <X size={19} />
        </button>

        <div className="voice-header">
          <div className={`voice-mic-badge ${isListening ? 'listening' : ''}`}>
            {isListening ? <Mic size={24} className="pulse-mic" /> : <MicOff size={24} />}
          </div>
          <div>
            <span className="mini-label">Yatra Saathi Assistant</span>
            <h2 id="voice-modal-title">Speak to Yatra Saathi</h2>
          </div>
          <span className="language-badge">{currentLanguage}</span>
        </div>

        <p className="voice-disclaimer">
          🔒 <strong>Privacy:</strong> Raw microphone audio is never permanently stored. Voice inputs are validated by the same authoritative travel business rules.
        </p>

        {/* Listening / Preview State */}
        <div className="voice-interaction-box">
          {isListening ? (
            <div className="listening-indicator">
              <span className="pulse-dot" />
              <span>Listening in {currentLanguage}... Speak now</span>
            </div>
          ) : (
            <div className="idle-indicator">
              <span>Click the microphone button to speak or type your request below.</span>
            </div>
          )}

          {transcript && (
            <div className="transcript-preview">
              <span className="preview-label">Live Transcription:</span>
              <p className="preview-text">"{transcript}"</p>
            </div>
          )}

          <div className="voice-controls-row">
            {isListening ? (
              <button
                type="button"
                className="voice-control-btn stop-btn"
                onClick={stopListening}
                aria-label="Stop listening"
              >
                <MicOff size={16} /> Stop Listening
              </button>
            ) : (
              <button
                type="button"
                className="voice-control-btn listen-btn"
                onClick={startListening}
                aria-label="Start listening"
              >
                <Mic size={16} /> {transcript ? 'Retry Speaking' : 'Start Speaking'}
              </button>
            )}

            {transcript && !isListening && (
              <button
                type="button"
                className="modal-primary voice-send-btn"
                onClick={() => void handleSendTranscript(transcript)}
                disabled={processing}
              >
                {processing ? <span className="spinner" /> : <><Send size={15} /> Send Voice Input</>}
              </button>
            )}
          </div>
        </div>

        {/* Material Action Confirmation Dialog (Section 14) */}
        {pendingConfirmation && (
          <div className="material-confirmation-box" role="alert">
            <div className="confirmation-header">
              <AlertTriangle size={20} className="warning-icon" />
              <strong>Explicit User Confirmation Required</strong>
            </div>
            <p className="confirmation-prompt">{pendingConfirmation.prompt}</p>
            <div className="confirmation-action-buttons">
              <button
                type="button"
                className="modal-primary confirm-action-btn"
                onClick={handleConfirmMaterialAction}
              >
                <Check size={16} /> Confirm Action
              </button>
              <button
                type="button"
                className="modal-secondary reject-action-btn"
                onClick={handleRejectMaterialAction}
              >
                <X size={16} /> Cancel Action
              </button>
            </div>
          </div>
        )}

        {/* Text Fallback Alternative (Section 15) */}
        <div className="voice-text-fallback">
          <label htmlFor="voice-manual-input" className="mini-label">
            Keyboard Alternative / Text Fallback
          </label>
          <div className="fallback-input-row">
            <input
              id="voice-manual-input"
              type="text"
              placeholder='e.g. "जयपुर के लिए यात्रा योजना बनाओ" or "Plan a trip to Jaipur"'
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault()
                  void handleSendTranscript(manualText)
                }
              }}
            />
            <button
              type="button"
              className="text-fallback-send"
              onClick={() => void handleSendTranscript(manualText)}
              disabled={!manualText.trim() || processing}
              aria-label="Submit text"
            >
              <Send size={15} />
            </button>
          </div>
        </div>

        {/* TTS Control */}
        {isSpeaking && (
          <div className="tts-status-bar">
            <Volume2 size={16} className="speaking-icon" />
            <span>Yatra Saathi is speaking...</span>
            <button
              type="button"
              className="tts-stop-btn"
              onClick={stopSpeaking}
              title="Stop speaking"
            >
              <VolumeX size={14} /> Stop Speech
            </button>
          </div>
        )}

        {error && (
          <div className="modal-result signin-error" role="alert">
            {error}
          </div>
        )}
      </section>
    </div>
  )
}
