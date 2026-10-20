import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  ArrowRight, ArrowUpRight, Bell, CalendarDays, Check, ChevronDown, CircleHelp,
  Eye, EyeOff, Heart, Hotel, IdCard, Lock, LogOut, Mail, MapPin, Maximize2, Menu, Mic, Minus, Moon, Plane, Plus, Send, ShieldAlert, ShieldCheck, Sparkles, Sun, Trees, UserPlus, UserRound, Users, Utensils, Wallet, X,
} from 'lucide-react'
import { PrivacyPolicyPage } from './PrivacyPolicyPage'
import { TermsPage } from './TermsPage'
import { NotFoundPage } from './NotFoundPage'
import { BrandLogo } from './BrandLogo'
import { conciergeService, destinationPhoto } from '../services/conciergeService'
import { authService, authErrorMessage, type AuthUser } from '../services/authService'
import { ApiError, apiData } from '../services/apiClient'
import { briefFromMessage, findOrigin } from '../services/briefFromMessage'
import { useCurrencies } from '../services/currencyService'
import { hasExplicitRegistrationConsent } from '../utils/authValidation'
import { itineraryFromCart } from '../services/itineraryFromCart'
import { chosenOption, dateSuggestions, historyFromEvents, type DateSuggestion } from '../services/historyFromEvents'
import { normalizeMoney, sessionService, type AgentSession, type AuditEvent, type AuditVerification, type Booking, type Cart, type Confirmation } from '../services/sessionService'
import AgentSessionPanel from './AgentSessionPanel'
import ExplorePage from './ExplorePage'
import MyTripsPage, { type Trip } from './MyTripsPage'
import StayDetailModal from './StayDetailModal'
import TravelMap from './TravelMap'
import StructuredTripPlanCard from './StructuredTripPlanCard'
import TravelOptionsComparisonCard from './TravelOptionsComparisonCard'
import { PreferencesPanel } from './PreferencesPanel'
import { DestinationExplorerCard } from './DestinationExplorerCard'
import { HotelExplorerCard } from './HotelExplorerCard'
import TripOptions, { isTripOptions, type TripOption } from './TripOptions'
import PushPanel from './PushPanel'
import BookingReviewModal from './BookingReviewModal'
import TripPackModal from './TripPackModal'
import VoiceAssistantModal from './VoiceAssistantModal'
import NotificationCenterModal from './NotificationCenterModal'
import EmergencyAssistanceModal from './EmergencyAssistanceModal'
import { phase6Service } from '../services/phase6Service'
// three.js is large: load the 360° viewer only when someone opens it.
const XRViewer = lazy(() => import('./XRViewer'))
import { useLanguage } from '../i18n/LanguageContext'
import type { BudgetSummary, FlightOption, HotelOption, ItineraryActivity, ItineraryAlternativeOption, ItineraryStop, PlanDiff, StructuredTripPlan, TravelOption, TripRequest } from '../types/travel'
import { itineraryService, normalizeTripPlan } from '../services/itineraryService'
import { decimalToMinorUnits, formatMoney, formatShortDate, subtractMoney } from '../utils/format'
import { addDays, laterDate, todayDateOnly, tripDateIssue, type TripDateIssue } from '../utils/dates'
import FlightSearchPage from './FlightSearchPage'

const initialRequest: TripRequest = {
  destination: '', startDate: '2026-11-16', endDate: '2026-11-20', travellers: 2,
  budget: '25000.00', currency: 'INR', preferences: '',
}

const supportedPromptSuggestions = [
  { label: 'Mumbai → Lucknow · 2 adults', prompt: 'Plan a trip from Mumbai to Lucknow for 2 adults from 16 to 19 November 2026 under ₹45000.' },
  { label: 'Ahmedabad → Bengaluru', prompt: 'Plan a trip from Ahmedabad to Bengaluru for 2 adults from 14 October 2026 to 19 October 2026 under ₹100000.' },
  { label: 'Ahmedabad → Hyderabad', prompt: 'Plan a trip from Ahmedabad to Hyderabad for 2 adults from 15 to 18 October 2026 under ₹55000.' },
  { label: 'Ahmedabad → Lucknow · 5 nights', prompt: 'Plan a trip from Ahmedabad to Lucknow for 2 adults from 7 to 12 November 2026 under ₹80000.' },
  { label: 'Bengaluru → Jaipur', prompt: 'Plan a trip from Bengaluru to Jaipur for 2 adults from 4 to 9 November 2026 under ₹75000.' },
  { label: 'Chennai → Pune', prompt: 'Plan a trip from Chennai to Pune for 2 adults from 3 Nov to 7 Nov 2026 under ₹65000.' },
  { label: 'Ahmedabad → New Delhi', prompt: 'Plan a trip from Ahmedabad to New Delhi for 2 adults from 3 to 5 November 2026 under ₹45000.' },
  { label: 'Lucknow · 2 nights', prompt: 'Plan a trip from Ahmedabad to Lucknow for 2 adults from 10 to 12 November 2026 under ₹35000.' },
  { label: 'Mumbai → Kolkata · 5 adults', prompt: 'Plan a trip from Mumbai to Kolkata for 5 adults from 12 to 16 October 2026 under ₹50000.' },
  { label: 'Mumbai → Lucknow · 3 adults', prompt: 'Plan a 3-night trip from Mumbai to Lucknow on 16 November 2026 for 3 adults under ₹90000.' },
]

type ChatMessage = { role: 'assistant' | 'user'; content: string; options?: TripOption[]; suggestions?: DateSuggestion[] }
const LAST_SESSION_KEY = 'yatra-last-session'
const POLL_INTERVAL_MS = 1500
// With no agent process connected, a session stays `executing`; stop polling and say so.
const STALL_AFTER_MS = 60_000
type NotificationKey = 'tripUpdates' | 'bookingUpdates' | 'priceChanges' | 'itineraryReminders' | 'agentSuggestions'
type NotificationPreferences = Record<NotificationKey, boolean>
const defaultNotificationPreferences: NotificationPreferences = {
  tripUpdates: true, bookingUpdates: true, priceChanges: false, itineraryReminders: true, agentSuggestions: false,
}

function loadNotificationPreferences(): NotificationPreferences {
  try {
    const saved = JSON.parse(localStorage.getItem('yatra-notification-preferences') ?? '{}') as Partial<NotificationPreferences>
    return Object.fromEntries(Object.entries(defaultNotificationPreferences).map(([key, fallback]) => [key, typeof saved[key as NotificationKey] === 'boolean' ? saved[key as NotificationKey] : fallback])) as NotificationPreferences
  } catch { return defaultNotificationPreferences }
}

export default function App() {
  const { language, options: languageOptions, setLanguage, t } = useLanguage()
  const [request, setRequest] = useState(initialRequest)
  const [hotels, setHotels] = useState<HotelOption[]>([])
  const [itinerary, setItinerary] = useState<ItineraryStop[]>([])
  const [budget, setBudget] = useState<BudgetSummary | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selectedHotel, setSelectedHotel] = useState<HotelOption | null>(null)
  const [originCity, setOriginCity] = useState<string>('')
  const [originCoords, setOriginCoords] = useState<{ lat: number; lng: number } | null>(null)
  const [destinationCoords, setDestinationCoords] = useState<{ lat: number; lng: number } | null>(null)
  const [structuredPlan, setStructuredPlan] = useState<StructuredTripPlan | null>(null)
  const [planAlternatives, setPlanAlternatives] = useState<ItineraryAlternativeOption[]>([])
  const [selectedAlternativeId, setSelectedAlternativeId] = useState<string>('balanced')
  const [planExecutionSteps, setPlanExecutionSteps] = useState<string[]>([])
  const [replanningPlan, setReplanningPlan] = useState(false)
  const [replanError, setReplanError] = useState<string | null>(null)
  const [selectedActivity, setSelectedActivity] = useState<ItineraryActivity | null>(null)
  const [activeDayFilter, setActiveDayFilter] = useState<number | null>(null)
  const [comparisonOptions, setComparisonOptions] = useState<TravelOption[]>([])
  const [comparisonSummary, setComparisonSummary] = useState<string>('')
  const [comparisonTradeOffs, setComparisonTradeOffs] = useState<string[]>([])
  const [comparingOptions, setComparingOptions] = useState<boolean>(false)
  const [pendingPlanDiff, setPendingPlanDiff] = useState<PlanDiff | null>(null)
  const [pendingOptimizedOption, setPendingOptimizedOption] = useState<TravelOption | null>(null)
  const [holdMessage, setHoldMessage] = useState('')
  const [holding, setHolding] = useState(false)
  const [mobileOpen, setMobileOpen] = useState(false)
  const [showPreferencesModal, setShowPreferencesModal] = useState(false)
  const [reviewingPlan, setReviewingPlan] = useState<{ id: string; version: number } | null>(null)
  const [activeTripPackBookingId, setActiveTripPackBookingId] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const [chatDraft, setChatDraft] = useState('')
  const [currentPath, setCurrentPath] = useState<string>(() => typeof window !== 'undefined' ? window.location.pathname : '/')

  useEffect(() => {
    const handlePopState = () => {
      setCurrentPath(window.location.pathname)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  useEffect(() => {
    if (currentPath === '/' || currentPath === '' || currentPath.startsWith('/#')) {
      document.title = 'Yatra Saathi — Your Travel Companion'
      const metaDesc = document.querySelector('meta[name="description"]')
      if (metaDesc) {
        metaDesc.setAttribute(
          'content',
          'Plan thoughtful trips with Yatra Saathi, your intelligent travel companion. Custom itineraries, verified stays, budget tracking, and interactive mapping.'
        )
      }
    }
  }, [currentPath])

  const navigate = useCallback((path: string) => {
    if (typeof window !== 'undefined') {
      if (window.location.pathname !== path) {
        window.history.pushState({}, '', path)
      }
      setCurrentPath(path)
      window.scrollTo({ top: 0, behavior: 'smooth' })
    }
  }, [])

  const currencyList = useCurrencies()
  // Every currency the backend can price a trip in (it converts at its demo rates).
  const currencyOptions = (currencyList.currencies.some((c) => c.code === request.currency) ? currencyList.currencies : [{ code: request.currency }, ...currencyList.currencies])
    .map((c) => <option key={c.code} value={c.code}>{c.code}</option>)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([{ role: 'assistant', content: t('agent.greeting') }])
  useEffect(() => {
    setChatMessages((messages) => messages.length === 1 && messages[0].role === 'assistant' ? [{ role: 'assistant', content: t('agent.greeting') }] : messages)
  }, [language.tag, t])
  const [agentSteps, setAgentSteps] = useState<string[]>([])
  const [agentLoading, setAgentLoading] = useState(false)
  const [briefEditing, setBriefEditing] = useState(false)
  const [signInOpen, setSignInOpen] = useState(false)
  const [signInError, setSignInError] = useState('')
  const [signingIn, setSigningIn] = useState(false)
  const [authMode, setAuthMode] = useState<'signin' | 'register'>('signin')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [forgotPasswordNote, setForgotPasswordNote] = useState('')
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null)
  const [agentSession, setAgentSession] = useState<AgentSession | null>(null)
  const [sessionEvents, setSessionEvents] = useState<AuditEvent[]>([])
  const [sessionCart, setSessionCart] = useState<Cart | null>(null)
  const [confirmation, setConfirmation] = useState<Confirmation | null>(null)
  const [booking, setBooking] = useState<Booking | null>(null)
  const [verification, setVerification] = useState<AuditVerification | null>(null)
  const [stalled, setStalled] = useState(false)
  const [deciding, setDeciding] = useState(false)
  const [decisionError, setDecisionError] = useState('')
  const pollStartedAt = useRef(0)
  const announced = useRef('')
  const [notificationsOpen, setNotificationsOpen] = useState(false)
  const [notificationPreferences, setNotificationPreferences] = useState(loadNotificationPreferences)
  const [showVoiceModal, setShowVoiceModal] = useState(false)
  const [showNotificationCenter, setShowNotificationCenter] = useState(false)
  const [showEmergencyModal, setShowEmergencyModal] = useState(false)
  const [unreadCount, setUnreadCount] = useState(0)

  const refreshUnreadCount = useCallback(async () => {
    if (!currentUser) {
      setUnreadCount(0)
      return
    }
    try {
      const count = await phase6Service.getUnreadCount()
      setUnreadCount(count)
    } catch {
      // ignore
    }
  }, [currentUser])

  useEffect(() => {
    void refreshUnreadCount()
    const interval = window.setInterval(() => {
      void refreshUnreadCount()
    }, 15000)
    return () => window.clearInterval(interval)
  }, [refreshUnreadCount, currentUser])

  useEffect(() => {
    if (currentUser) {
      void phase6Service.getLanguagePreference().then((pref) => {
        if (pref?.language_code && ['en-IN', 'hi-IN', 'ta-IN'].includes(pref.language_code)) {
          setLanguage(pref.language_code)
        }
      }).catch(() => undefined)
    }
  }, [currentUser, setLanguage])

  const [theme, setTheme] = useState<'light' | 'dark'>(() => localStorage.getItem('yatra-theme') === 'dark' ? 'dark' : 'light')
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('yatra-theme', theme)
  }, [theme])
  useEffect(() => {
    localStorage.setItem('yatra-notification-preferences', JSON.stringify(notificationPreferences))
  }, [notificationPreferences])
  const itinerarySampleDate = new Date(2026, 10, 17)

  async function refreshResults(nextRequest = request) {
    setLoading(true); setError(''); setNotice('')
    try {
      if (!conciergeService.isMock) {
        // Live mode: budget and plan come from the agent session, not from these preview routes.
        setHotels(await conciergeService.searchHotels(nextRequest))
        return
      }
      const [options, stops, currentBudget] = await Promise.all([
        conciergeService.searchHotels(nextRequest), conciergeService.getItinerary(nextRequest), conciergeService.getBudget(nextRequest),
      ])
      setHotels(options); setItinerary(stops); setBudget(currentBudget)
    } catch (cause) {
      // The backend has no human search route yet (open decision); say so rather than show a bare 404.
      if (cause instanceof ApiError && cause.status === 404) setError(t('stays.searchUnavailable'))
      else setError(cause instanceof Error ? cause.message : 'Could not load trip suggestions. Please try again.')
    } finally { setLoading(false) }
  }

  useEffect(() => { void refreshResults() }, [])
  useEffect(() => {
    let active = true
    if (originCity) {
      void conciergeService.getCityCoordinates(originCity).then((coords) => {
        if (active) setOriginCoords(coords)
      })
    } else {
      setOriginCoords(null)
    }
    return () => { active = false }
  }, [originCity])

  useEffect(() => {
    let active = true
    if (request.destination) {
      void conciergeService.getCityCoordinates(request.destination).then((coords) => {
        if (active) setDestinationCoords(coords)
      })
    } else {
      setDestinationCoords(null)
    }
    return () => { active = false }
  }, [request.destination])

  useEffect(() => {
    if (sessionCart) {
      const flightItem = sessionCart.items.find((it) => it.details?.type === 'flight')
      if (flightItem?.details && flightItem.details.type === 'flight' && flightItem.details.origin_city) {
        setOriginCity(flightItem.details.origin_city)
      }
    }
  }, [sessionCart])

  useEffect(() => {
    let active = true
    if (agentSession?.sessionId) {
      void apiData<{ itinerary: StructuredTripPlan | null }>(`/api/v1/sessions/${agentSession.sessionId}/itinerary`)
        .then((res) => {
          if (active && res.itinerary) setStructuredPlan(normalizeTripPlan(res.itinerary))
        })
        .catch(() => {
          // fallback gracefully
        })
    } else if (request.destination && request.startDate && request.endDate) {
      const sDate = new Date(`${request.startDate}T12:00:00`)
      const eDate = new Date(`${request.endDate}T12:00:00`)
      const numDays = Math.max(Math.round((eDate.getTime() - sDate.getTime()) / (1000 * 3600 * 24)) + 1, 1)
      const days = Array.from({ length: numDays }, (_, i) => {
        const d = new Date(sDate)
        d.setDate(d.getDate() + i)
        const dStr = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
        return {
          date: dStr,
          dayNumber: i + 1,
          title: i === 0 ? 'Arrival & Welcome' : i === numDays - 1 ? 'Departure' : `Explore ${request.destination}`,
          activities: [],
          locations: [request.destination],
        }
      })
      setStructuredPlan({
        id: 'preview_plan',
        title: `${originCity || 'Origin'} to ${request.destination} Trip`,
        origin: originCity || 'Origin',
        destination: request.destination,
        startDate: request.startDate,
        endDate: request.endDate,
        travellers: request.travellers,
        currency: request.currency || 'INR',
        budget: request.budget || null,
        totalEstimatedCost: request.budget || null,
        transport: [],
        accommodation: selectedHotel ? [{
          hotelName: selectedHotel.name,
          address: selectedHotel.address || null,
          checkInDate: request.startDate,
          checkOutDate: request.endDate,
          knownPrice: selectedHotel.price,
          currency: selectedHotel.currency,
          latitude: selectedHotel.latitude ?? null,
          longitude: selectedHotel.longitude ?? null,
        }] : [],
        days,
        status: 'draft',
      })
    } else {
      setStructuredPlan(null)
    }
    return () => { active = false }
  }, [agentSession?.sessionId, sessionCart, request.destination, request.startDate, request.endDate, request.travellers, request.budget, request.currency, originCity, selectedHotel])

  const handleGeneratePlan = useCallback(async () => {
    if (!currentUser) {
      setSignInError('')
      setSignInOpen(true)
      return
    }
    if (!request.destination) return
    setReplanningPlan(true)
    setReplanError(null)
    try {
      const res = await itineraryService.generate({
        sessionId: agentSession?.sessionId,
        origin: originCity || 'Mumbai',
        destination: request.destination,
        startDate: request.startDate,
        endDate: request.endDate,
        travellers: request.travellers,
        budget: request.budget,
        currency: request.currency || 'INR',
        preferences: request.preferences,
        hotelId: selectedHotel?.hotelId,
      })
      setStructuredPlan(res.activePlan)
      setPlanAlternatives(res.alternatives)
      setPlanExecutionSteps(res.executionSteps)
      setSelectedAlternativeId('balanced')
      setNotice(`Itinerary draft ready for ${request.destination} with ${res.alternatives.length} options!`)
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Itinerary generation failed.'
      setReplanError(msg)
    } finally {
      setReplanningPlan(false)
    }
  }, [currentUser, request, originCity, agentSession?.sessionId, selectedHotel?.hotelId])

  const handleSelectAlternative = useCallback(async (optionId: string) => {
    if (!structuredPlan?.id || structuredPlan.id === 'preview_plan') {
      const found = planAlternatives.find((a) => a.optionId === optionId)
      if (found) {
        setStructuredPlan(found.plan)
        setSelectedAlternativeId(optionId)
      }
      return
    }
    setReplanningPlan(true)
    setReplanError(null)
    try {
      const res = await itineraryService.selectAlternative(structuredPlan.id, optionId)
      setStructuredPlan(res.itinerary)
      setSelectedAlternativeId(optionId)
      setNotice(`Switched active plan to ${optionId} option.`)
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Could not switch option.'
      setReplanError(msg)
    } finally {
      setReplanningPlan(false)
    }
  }, [structuredPlan?.id, planAlternatives])

  const handleReplan = useCallback(async (instruction: string) => {
    if (!structuredPlan?.id || structuredPlan.id === 'preview_plan') {
      await handleGeneratePlan()
      return
    }
    setReplanningPlan(true)
    setReplanError(null)
    try {
      const res = await itineraryService.replan(structuredPlan.id, { instruction })
      setStructuredPlan(res.itinerary)
      setNotice(`Itinerary updated: "${instruction}"`)
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Replanning failed.'
      setReplanError(msg)
    } finally {
      setReplanningPlan(false)
    }
  }, [structuredPlan?.id, handleGeneratePlan])

  const handleRegenerate = useCallback(async () => {
    if (!structuredPlan?.id || structuredPlan.id === 'preview_plan') {
      await handleGeneratePlan()
      return
    }
    setReplanningPlan(true)
    setReplanError(null)
    try {
      const res = await itineraryService.regenerate(structuredPlan.id)
      setStructuredPlan(res.itinerary)
      setNotice('Daily activities regenerated successfully.')
    } catch (cause) {
      const msg = cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : 'Regeneration failed.'
      setReplanError(msg)
    } finally {
      setReplanningPlan(false)
    }
  }, [structuredPlan?.id, handleGeneratePlan])

  const handleCompareOptions = useCallback(async (catFilter?: any) => {
    if (!request.destination || !request.startDate || !request.endDate) return
    setComparingOptions(true)
    try {
      const res = await itineraryService.compareOptions({
        origin: originCity || 'Mumbai',
        destination: request.destination,
        startDate: request.startDate,
        endDate: request.endDate,
        travellers: request.travellers,
        currency: request.currency || 'INR',
        budget: request.budget,
        preferences: request.preferences,
        categoryFilter: catFilter,
        maxOptions: 4,
      })
      if (res.feasible) {
        setComparisonOptions(res.options)
        setComparisonSummary(res.recommendationSummary)
        setComparisonTradeOffs(res.tradeOffAnalysis)
        setNotice(`Generated ${res.options.length} compared travel packages with trade-off analysis.`)
      } else {
        setNotice(res.noFeasibleReason || 'No feasible combinations found for these constraints.')
      }
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : 'Comparison request failed.'
      setError(msg)
    } finally {
      setComparingOptions(false)
    }
  }, [originCity, request])

  const handleOptimize = useCallback(async (objective: string, allowedChanges?: any) => {
    if (!structuredPlan?.id || structuredPlan.id === 'preview_plan') {
      await handleCompareOptions()
      return
    }
    setComparingOptions(true)
    try {
      const res = await itineraryService.optimizeTrip(structuredPlan.id, {
        itineraryId: structuredPlan.id,
        objective,
        allowedChanges,
        targetBudget: request.budget,
        preferences: request.preferences,
      })
      if (res.feasible && res.diff) {
        setPendingPlanDiff(res.diff)
        setPendingOptimizedOption(res.optimizedOption ?? null)
        setNotice(res.explanation)
      } else {
        setNotice(res.explanation || 'No feasible optimization found for target budget.')
      }
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : 'Optimization failed.'
      setError(msg)
    } finally {
      setComparingOptions(false)
    }
  }, [structuredPlan?.id, request.budget, request.preferences, handleCompareOptions])

  const handleApplyTravelOption = useCallback(async (opt: TravelOption) => {
    if (!structuredPlan?.id || structuredPlan.id === 'preview_plan') {
      if (opt.hotel) {
        setSelectedHotel({
          hotelId: opt.hotel.hotelId,
          roomTypeId: opt.hotel.roomTypeId ?? '',
          inventoryIds: [],
          maxOccupancy: request.travellers || 2,
          name: opt.hotel.hotelName,
          city: request.destination,
          country: 'IN',
          description: '',
          imageUrl: '',
          roomName: opt.hotel.roomName ?? 'Standard Room',
          price: opt.hotel.totalHotelPrice,
          currency: opt.hotel.currency,
          nights: opt.hotel.nights,
          availableUnits: 1,
          latitude: opt.hotel.latitude,
          longitude: opt.hotel.longitude,
          address: opt.hotel.address ?? '',
          tags: [],
        })
      }
      setNotice(`Applied ${opt.label} (${opt.currency} ${opt.authoritativeTotal}).`)
      return
    }
    setReplanningPlan(true)
    try {
      const res = await itineraryService.applyTravelOption(structuredPlan.id, opt.id, opt)
      setStructuredPlan(res.itinerary)
      if (opt.hotel) {
        setSelectedHotel({
          hotelId: opt.hotel.hotelId,
          roomTypeId: opt.hotel.roomTypeId ?? '',
          inventoryIds: [],
          maxOccupancy: request.travellers || 2,
          name: opt.hotel.hotelName,
          city: request.destination,
          country: 'IN',
          description: '',
          imageUrl: '',
          roomName: opt.hotel.roomName ?? 'Standard Room',
          price: opt.hotel.totalHotelPrice,
          currency: opt.hotel.currency,
          nights: opt.hotel.nights,
          availableUnits: 1,
          latitude: opt.hotel.latitude,
          longitude: opt.hotel.longitude,
          address: opt.hotel.address ?? '',
          tags: [],
        })
      }
      setNotice(`Successfully updated itinerary with ${opt.label}! New authoritative total: ${res.itinerary.currency} ${res.itinerary.totalAuthoritativeCost}.`)
    } catch (cause) {
      const msg = cause instanceof Error ? cause.message : 'Could not apply option.'
      setError(msg)
    } finally {
      setReplanningPlan(false)
    }
  }, [structuredPlan?.id, request.destination])

  const handleConfirmDiff = useCallback(async () => {
    if (pendingOptimizedOption) {
      await handleApplyTravelOption(pendingOptimizedOption)
      setPendingPlanDiff(null)
      setPendingOptimizedOption(null)
    }
  }, [pendingOptimizedOption, handleApplyTravelOption])

  const handleDismissDiff = useCallback(() => {
    setPendingPlanDiff(null)
    setPendingOptimizedOption(null)
  }, [])

  const handleRefreshActivePlan = useCallback(async () => {
    if (structuredPlan?.id && structuredPlan.id !== 'preview_plan') {
      try {
        const res = await itineraryService.get(structuredPlan.id)
        if (res?.itinerary) setStructuredPlan(res.itinerary)
      } catch {
        // ignore
      }
    }
  }, [structuredPlan?.id])

  const handleSelectExplorerCoords = useCallback((lat: number, lng: number, title: string) => {
    setDestinationCoords({ lat, lng })
    document.querySelector('.yatra-travel-map-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    setNotice(`Focused map on ${title}`)
  }, [])

  const mapActivities = useMemo(() => {
    if (!structuredPlan?.days) return []
    const allActs = structuredPlan.days.flatMap((d) => d.activities)
    if (activeDayFilter !== null) {
      const day = structuredPlan.days.find((d) => d.dayNumber === activeDayFilter)
      return day ? day.activities : []
    }
    return allActs
  }, [structuredPlan, activeDayFilter])

  useEffect(() => {
    void authService.restore().then((user) => {
      setCurrentUser(user)
      // Bring back the last conversation after a reload (it is stored server-side).
      let last: string | null = null
      try { last = localStorage.getItem(LAST_SESSION_KEY) } catch { /* storage unavailable */ }
      if (user && last && !conciergeService.isMock) void restoreSession(last)
    })
  }, [])

  const liveBudget = useMemo<BudgetSummary | null>(() => agentSession
    ? { currency: agentSession.currency, total: agentSession.effectiveCap, committed: agentSession.committed, planned: agentSession.cartTotal }
    : null, [agentSession])
  const shownBudget = conciergeService.isMock ? budget : liveBudget
  const remaining = useMemo(() => {
    if (!shownBudget) return '0.00'
    return subtractMoney(shownBudget.total, shownBudget.committed, shownBudget.planned)
  }, [shownBudget])

  // One set of trip dates (YYYY-MM-DD): start = hotel check-in and outbound flight, end = hotel
  // check-out and return flight. The start may be today, and the end is at least one night later.
  const today = todayDateOnly()
  const dateIssue = tripDateIssue(request.startDate, request.endDate, today)
  const minEndDate = addDays(laterDate(request.startDate || today, today), 1)
  function dateIssueMessage(issue: TripDateIssue, scope: 'search' | 'brief', trip: TripRequest = request) {
    if (!issue) return ''
    return t(`${scope}.${issue === 'past' ? 'datePast' : 'dateOrder'}`)
      .replace('{start}', formatShortDate(trip.startDate, language.tag))
      .replace('{end}', formatShortDate(trip.endDate, language.tag))
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (dateIssue) { document.getElementById(dateIssue === 'past' ? 'start-date' : 'end-date')?.focus(); return }
    // Results render right under the search bar; bring them into view.
    document.getElementById('stays-results')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    await refreshResults(request)
  }

  const loadSession = useCallback(async (sessionId: string) => {
    const [session, events, cart, pending, done] = await Promise.all([
      sessionService.get(sessionId), sessionService.audit(sessionId), sessionService.cart(sessionId),
      sessionService.currentConfirmation(sessionId), sessionService.booking(sessionId),
    ])
    setAgentSession(session); setSessionEvents(events); setSessionCart(cart); setConfirmation(pending); setBooking(done)
    return { session, events, booking: done }
  }, [])

  // Poll while the agent runs; when it hands control back, turn the new state into a chat reply.
  useEffect(() => {
    if (!agentSession || agentSession.status !== 'executing' || stalled) return
    const sessionId = agentSession.sessionId
    const timer = window.setInterval(() => {
      if (Date.now() - pollStartedAt.current > STALL_AFTER_MS) { setStalled(true); return }
      void loadSession(sessionId).catch(() => undefined)
    }, POLL_INTERVAL_MS)
    return () => window.clearInterval(timer)
  }, [agentSession, stalled, loadSession])

  useEffect(() => {
    if (!agentSession || agentSession.status === 'executing') return
    const lastSeq = sessionEvents.length ? sessionEvents[sessionEvents.length - 1].seq : 0
    const key = `${agentSession.sessionId}:${agentSession.status}:${lastSeq}`
    if (announced.current === key) return
    announced.current = key
    let content = ''
    let options: TripOption[] | undefined
    let suggestions: DateSuggestion[] | undefined
    if (agentSession.status === 'awaiting_input') {
      const asked = [...sessionEvents].reverse().find((event) => event.eventType === 'CLARIFICATION_REQUESTED')?.input
      const question = asked?.question
      content = typeof question === 'string' && question ? question : t('session.msg.needInput')
      if (isTripOptions(asked?.options)) { options = asked.options; content = content.split('\n')[0] }
      suggestions = dateSuggestions(asked?.suggestions)
    } else if (agentSession.status === 'awaiting_confirmation') {
      // Recap: the chosen option's full details sit with the "ready to approve" message.
      content = t('session.msg.confirm')
      const picked = chosenOption(sessionEvents)
      if (picked) options = [picked]
    }
    else if (agentSession.status === 'completed') content = booking ? t('session.msg.booked').replace('{reference}', booking.bookingReference) : t('session.status.completed')
    else if (agentSession.status === 'failed') content = t(`session.error.${agentSession.lastErrorCode ?? 'unknown'}`)
    else if (agentSession.status === 'paused') content = t('session.status.paused')
    if (content) setChatMessages((current) => [...current, { role: 'assistant', content, options, suggestions }])
  }, [agentSession, sessionEvents, booking, t])

  // Only the newest set of options can be chosen; re-plan shortcuts once Yatra has something to change.
  const lastOptionsIndex = chatMessages.reduce((last, m, i) => (m.options ? i : last), -1)
  const canReplan = !conciergeService.isMock && !!agentSession && (agentSession.status === 'awaiting_confirmation'
    || (agentSession.status === 'awaiting_input' && lastOptionsIndex >= 0))

  // "Continue planning" in My trips: reopen that Yatra session here, with the brief matching it
  // (same budget, so the next message continues the session instead of starting a new one).
  async function resumeTrip(trip: Trip) {
    if (!trip.sessionId) return
    setRequest((current) => ({ ...current, destination: trip.destination, startDate: trip.startDate, endDate: trip.endDate,
      travellers: trip.partySize, budget: trip.budget, currency: trip.currency }))
    document.querySelector('.core-agent-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    await restoreSession(trip.sessionId, t('trip.resumed').replace('{title}', trip.title))
  }

  // Reopen a stored session: its whole conversation comes back from the audit trail.
  async function restoreSession(sessionId: string, intro?: string) {
    resetSession()
    try {
      const { session, events } = await loadSession(sessionId)
      const history = historyFromEvents(events, t).map(({ role, content, options, suggestions }) => ({ role, content, options, suggestions }))
      setChatMessages([{ role: 'assistant', content: t('agent.greeting') }, ...(intro ? [{ role: 'assistant' as const, content: intro }] : []), ...history])
      // The history already ends with the current state; don't announce it a second time.
      announced.current = `${session.sessionId}:${session.status}:${events.length ? events[events.length - 1].seq : 0}`
      rememberSession(sessionId)
    } catch {
      rememberSession(null)
      resetSession()
    }
  }

  function rememberSession(sessionId: string | null) {
    try { if (sessionId) localStorage.setItem(LAST_SESSION_KEY, sessionId); else localStorage.removeItem(LAST_SESSION_KEY) } catch { /* storage unavailable */ }
  }

  function resetSession() {
    setAgentSession(null); setSessionEvents([]); setSessionCart(null); setConfirmation(null); setBooking(null)
    setVerification(null); setStalled(false); setDecisionError(''); announced.current = ''
  }

  async function handleLiveChat(message: string) {
    if (!currentUser) {
      setChatMessages((current) => [...current, { role: 'assistant', content: t('session.needLogin') }])
      setSignInError(''); setSignInOpen(true)
      return
    }
    // Details stated in the message (destination, dates, guests, budget) update the brief first,
    // so the session's hard cap and constraints match what the user just asked for.
    const brief = briefFromMessage(message, request, conciergeService.destinations, currencyList.currencies.map((c) => c.code))
    if (JSON.stringify(brief) !== JSON.stringify(request)) setRequest(brief)
    const extractedOrigin = findOrigin(message, conciergeService.destinations)
    if (extractedOrigin) setOriginCity(extractedOrigin)
    // Impossible dates (in the brief or just typed) are never sent for planning, and never
    // swapped: say what is wrong and let the user choose.
    const briefIssue = tripDateIssue(brief.startDate, brief.endDate, todayDateOnly())
    if (briefIssue) {
      setChatMessages((current) => [...current, { role: 'user', content: message }, { role: 'assistant', content: dateIssueMessage(briefIssue, 'brief', brief) }])
      setChatDraft(''); setBriefEditing(true)
      return
    }
    const spendCap = normalizeMoney(brief.budget)
    if (!spendCap || spendCap === '0.00') {
      setChatMessages((current) => [...current, { role: 'assistant', content: t('session.badBudget') }])
      return
    }
    setChatMessages((current) => [...current, { role: 'user', content: message }])
    setChatDraft(''); setAgentLoading(true); setError('')
    try {
      let session = agentSession
      // If destination changed, start a fresh session for the new destination
      const destChanged = Boolean(
        brief.destination && session?.goalText && !session.goalText.toLowerCase().includes(brief.destination.toLowerCase())
      )
      // The brief's budget is the session's hard cap and a chat message can only lower it, so a
      // raised (or changed) budget while Yatra waits for an answer needs a fresh session.
      const capChanged = session?.status === 'awaiting_input' && session.spendCap !== spendCap
      if (!session || session.status === 'completed' || session.status === 'failed' || capChanged || destChanged) {
        resetSession()
        session = await sessionService.create(message, brief, language.tag, spendCap)
        rememberSession(session.sessionId)
      }
      try {
        await sessionService.sendMessage(session.sessionId, message)
      } catch (sendErr) {
        // Automatic recovery for stale/missing/expired session (e.g. backend restart, DB reset, or 404):
        if (
          sendErr instanceof ApiError &&
          (sendErr.status === 404 || sendErr.code === 'SESSION_ACCESS_DENIED' || sendErr.message.includes('no such session'))
        ) {
          resetSession()
          rememberSession(null)
          session = await sessionService.create(message, brief, language.tag, spendCap)
          rememberSession(session.sessionId)
          await sessionService.sendMessage(session.sessionId, message)
        } else {
          throw sendErr
        }
      }
      pollStartedAt.current = Date.now(); setStalled(false)
      await loadSession(session.sessionId)
    } catch (cause) {
      if (
        cause instanceof ApiError &&
        (cause.status === 404 || cause.code === 'SESSION_ACCESS_DENIED' || cause.message.includes('no such session'))
      ) {
        resetSession()
        rememberSession(null)
      }
      const text = cause instanceof ApiError && cause.code === 'INVALID_STATE' ? t('session.busy')
        : cause instanceof ApiError && cause.status === 401 ? t('session.needLogin')
          : cause instanceof ApiError && (cause.status === 404 || cause.message.includes('no such session'))
            ? 'Your planning session expired or was not found. Please try sending your message again to start a new plan.'
            : cause instanceof ApiError ? cause.message : t('auth.unreachable')
      setChatMessages((current) => [...current, { role: 'assistant', content: text }])
    } finally { setAgentLoading(false) }
  }

  async function handleDecision(approve: boolean) {
    if (!agentSession || !confirmation) return
    setDeciding(true); setDecisionError('')
    try {
      if (approve) await sessionService.approve(agentSession.sessionId, confirmation)
      else await sessionService.decline(agentSession.sessionId, confirmation.confirmationId)
    } catch (cause) {
      const code = cause instanceof ApiError ? cause.code : undefined
      const key = `session.refusal.${code}`
      setDecisionError(code && t(key) !== key ? t(key) : cause instanceof Error ? cause.message : t('auth.failed'))
    } finally {
      setDeciding(false)
      await loadSession(agentSession.sessionId).catch(() => undefined)
    }
  }

  async function handleChatSubmit(event: FormEvent) {
    event.preventDefault()
    const message = chatDraft.trim()
    if (!message || agentLoading) return
    const extractedOrigin = findOrigin(message, conciergeService.destinations)
    if (extractedOrigin) setOriginCity(extractedOrigin)
    if (!conciergeService.isMock) { await handleLiveChat(message); return }
    setChatMessages((current) => [...current, { role: 'user', content: message }])
    setChatDraft(''); setAgentLoading(true); setAgentSteps([]); setError(''); setHotels([]); setItinerary([]); setBudget(null)
    try {
      const turn = await conciergeService.sendAgentTurn(message, request, language.tag)
      setRequest(turn.tripRequest); setHotels(turn.hotels); setItinerary(turn.itinerary); setBudget(turn.budget)
      setAgentSteps(turn.toolSteps)
      setChatMessages((current) => [...current, { role: 'assistant', content: turn.assistantMessage }])
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The trip planner could not complete that request.')
      setChatMessages((current) => [...current, { role: 'assistant', content: 'I hit a connection problem. Please try again, or adjust the trip details and search directly.' }])
    } finally { setAgentLoading(false) }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (signingIn) return
    const form = event.currentTarget
    const values = new FormData(form)
    setSigningIn(true)
    setSignInError('')
    setForgotPasswordNote('')

    if (authMode === 'signin') {
      const identifier = String(values.get('identifier') || values.get('userId') || '').trim()
      const password = String(values.get('password') || '')
      // Legacy fallback if user enters user_id, display_name, email
      const legacyUserId = String(values.get('userId') || '').trim()
      const legacyName = String(values.get('displayName') || '').trim()
      const legacyEmail = String(values.get('email') || '').trim()

      if (!password && legacyUserId && legacyName && legacyEmail) {
        try {
          const user = await authService.login({ userId: legacyUserId, displayName: legacyName, email: legacyEmail })
          setCurrentUser(user); setSignInOpen(false); form.reset()
          setNotice(t('auth.welcome').replace('{name}', user.displayName))
        } catch (cause) {
          setSignInError(authErrorMessage(cause))
        } finally {
          setSigningIn(false)
        }
        return
      }

      if (!identifier) {
        setSignInError('Please enter your email or username.')
        setSigningIn(false)
        return
      }
      if (!password) {
        setSignInError('Please enter your password.')
        setSigningIn(false)
        return
      }

      try {
        const user = await authService.login({ identifier, password })
        setCurrentUser(user)
        setSignInOpen(false)
        form.reset()
        setNotice(t('auth.welcome').replace('{name}', user.displayName))
      } catch (cause) {
        setSignInError(authErrorMessage(cause))
        const pwInput = form.querySelector<HTMLInputElement>('#signin-password')
        if (pwInput) pwInput.value = ''
      } finally {
        setSigningIn(false)
      }
    } else {
      // Register Mode
      const fullName = String(values.get('fullName') || '').trim()
      const username = String(values.get('username') || '').trim().toLowerCase()
      const email = String(values.get('email') || '').trim().toLowerCase()
      const password = String(values.get('password') || '')
      const confirmPassword = String(values.get('confirmPassword') || '')
      const termsCheckbox = form.querySelector<HTMLInputElement>('#register-terms')
      const agreeTerms = hasExplicitRegistrationConsent(termsCheckbox?.checked)

      if (fullName.length < 2) {
        setSignInError('Please enter your full name (at least 2 characters).')
        setSigningIn(false)
        return
      }
      if (!/^[a-z0-9_]{3,30}$/.test(username)) {
        setSignInError('Username must be 3-30 lowercase characters (letters, numbers, underscores).')
        setSigningIn(false)
        return
      }
      if (!email || !email.includes('@') || email.length < 5) {
        setSignInError('Please enter a valid email address.')
        setSigningIn(false)
        return
      }
      if (password.length < 8) {
        setSignInError('Password must be at least 8 characters long.')
        setSigningIn(false)
        return
      }
      if (password !== confirmPassword) {
        setSignInError('Passwords do not match. Please verify both fields.')
        setSigningIn(false)
        return
      }
      if (!agreeTerms) {
        setSignInError('Please agree to the Yatra Saathi Terms and Privacy notice.')
        setSigningIn(false)
        return
      }

      try {
        const user = await authService.register({ fullName, username, email, password })
        setCurrentUser(user)
        setSignInOpen(false)
        form.reset()
        setNotice(`Account created successfully! Welcome to Yatra, ${user.displayName}.`)
      } catch (cause) {
        setSignInError(authErrorMessage(cause))
        const pwInput = form.querySelector<HTMLInputElement>('#register-password')
        const confirmInput = form.querySelector<HTMLInputElement>('#register-confirm-password')
        if (pwInput) pwInput.value = ''
        if (confirmInput) confirmInput.value = ''
      } finally {
        setSigningIn(false)
      }
    }
  }

  function handleSignOut() {
    authService.logout(); setCurrentUser(null); resetSession(); rememberSession(null)
    setChatMessages([{ role: 'assistant', content: t('agent.greeting') }]); setNotice(t('auth.signedOut'))
  }

  const closeStay = useCallback(() => setSelectedHotel(null), [])

  // "Plan this trip with Yatra" from the stay page: point the brief at the hotel's city and
  // pre-fill the chat, so the user only has to add their departure city and send.
  function planStay(hotel: HotelOption) {
    const day = (value: string) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }).format(new Date(`${value}T12:00:00`))
    setRequest((current) => ({ ...current, destination: hotel.city }))
    setChatDraft(`Plan a trip from <your city> to ${hotel.city} from ${day(request.startDate)} to ${day(request.endDate)} for ${request.travellers} ${request.travellers === 1 ? 'person' : 'people'}`)
    setSelectedHotel(null)
    window.setTimeout(() => {
      const input = document.getElementById('chat-input') as HTMLTextAreaElement | null
      input?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      const at = input?.value.indexOf('<your city>') ?? -1
      input?.focus()
      if (input && at >= 0) input.setSelectionRange(at, at + '<your city>'.length)
    }, 50)
  }

  async function handleHold() {
    if (!selectedHotel) return
    setHolding(true); setHoldMessage('')
    try {
      const result = await conciergeService.createHold(selectedHotel.hotelId)
      setHoldMessage(result.message)
    } catch (cause) {
      setHoldMessage(cause instanceof Error ? cause.message : 'Could not request a hold.')
    } finally { setHolding(false) }
  }

  function update<K extends keyof TripRequest>(key: K, value: TripRequest[K]) {
    setRequest((current) => ({ ...current, [key]: value }))
  }

  // The trip keeps the currency the user chose: the backend converts local prices into it.
  function updateDestination(destination: string) {
    setRequest((current) => ({ ...current, destination }))
  }

  if (currentPath === '/privacy') {
    return <PrivacyPolicyPage onNavigate={navigate} />
  }
  if (currentPath === '/terms') {
    return <TermsPage onNavigate={navigate} />
  }
  if (currentPath !== '/' && currentPath !== '' && !currentPath.startsWith('/#')) {
    return <NotFoundPage onNavigate={navigate} />
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" onClick={(e) => { e.preventDefault(); navigate('/'); window.scrollTo({ top: 0, behavior: 'smooth' }) }} aria-label="Yatra Saathi home"><BrandLogo size="md" /></a>
        <nav className={`nav-links ${mobileOpen ? 'nav-open' : ''}`} aria-label="Main navigation">
          <a className="nav-link active" href="#plan" onClick={() => { setMobileOpen(false); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>{t('nav.plan')}</a>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.querySelector('.yatra-travel-map-card')?.scrollIntoView({ behavior: 'smooth' }) }}>Map</button>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.getElementById('my-trips')?.scrollIntoView({ behavior: 'smooth' }) }}>{t('nav.trips')}</button>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.getElementById('explore')?.scrollIntoView({ behavior: 'smooth' }) }}>{t('nav.explore')}</button>
          <button className="nav-link" onClick={() => { setMobileOpen(false); document.getElementById('flights')?.scrollIntoView({ behavior: 'smooth' }) }}>{t('flight.nav')}</button>
          <button className="nav-link" onClick={() => { setMobileOpen(false); setShowPreferencesModal(true) }}>Preferences</button>
        </nav>
        <div className="topbar-actions">
          <label className="language-select-wrap" title="Choose interface language">
            <span className="language-dot" />
            <select
              className="language-select"
              value={language.tag}
              onChange={(event) => {
                setLanguage(event.target.value)
                if (currentUser) void phase6Service.setLanguagePreference(event.target.value).catch(() => undefined)
              }}
              aria-label="Interface language"
            >
              {languageOptions.map((item) => <option key={item.tag} value={item.tag}>{item.nativeName}</option>)}
            </select>
            <ChevronDown size={14} />
          </label>
          <button className="theme-toggle" onClick={() => setTheme((current) => current === 'light' ? 'dark' : 'light')} aria-label={t(theme === 'light' ? 'theme.switchDark' : 'theme.switchLight')} title={t(theme === 'light' ? 'theme.switchDark' : 'theme.switchLight')}>{theme === 'light' ? <Moon size={17} /> : <Sun size={17} />}</button>
          <button className="voice-topbar-button" onClick={() => setShowVoiceModal(true)} title="Speak to Yatra Saathi (Voice Assistant)" aria-label="Voice Assistant"><Mic size={14} /> <span>Voice</span></button>
          <button className="notifications-button" style={{ position: 'relative' }} aria-label={t('notifications.open')} title={t('notifications.open')} onClick={() => setShowNotificationCenter(true)}><Bell size={17} />{unreadCount > 0 && <span className="unread-bell-badge">{unreadCount}</span>}</button>
          <button className="emergency-topbar-button" onClick={() => setShowEmergencyModal(true)} title="Emergency Assistance (SOS)" aria-label="Emergency Assistance"><ShieldAlert size={14} /> <span>SOS</span></button>
          <div className="auth-header-actions">
            {currentUser
              ? <><span className="signed-in-user" title={`${currentUser.displayName} · ${currentUser.email} · ${currentUser.userId}`}><span className="signed-in-initial" aria-hidden="true">{currentUser.displayName.trim().charAt(0).toUpperCase()}</span><span className="signed-in-name">{currentUser.displayName}</span></span><button className="sign-in-button" onClick={handleSignOut} aria-label={t('auth.signOut')} title={t('auth.signOut')}><LogOut size={16} /> <span>{t('auth.signOut')}</span></button></>
              : <button className="sign-in-button" onClick={() => { setSignInError(''); setSignInOpen(true) }}><UserRound size={16} /> <span>{t('nav.signIn')}</span></button>}
          </div>
          <button className="mobile-menu icon-button" aria-label={mobileOpen ? t('nav.closeMenu') : t('nav.openMenu')} onClick={() => setMobileOpen(!mobileOpen)}>{mobileOpen ? <X size={20} /> : <Menu size={20} />}</button>
        </div>
      </header>

      {notice && <div className="notice" role="status">{notice}<button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={15} /></button></div>}

      <main id="home" className="main-content">
        <section className="hero-row" id="plan">
          <div className="hero-copy">
            <div className="eyebrow"><span className="eyebrow-line" /> {t('hero.eyebrow')}</div>
            <h1>{t('hero.title1')}<br /><em>{t('hero.title2')}</em></h1>
            <p className="hero-intro">{t('hero.intro')}</p>
            <div className="trust-note"><span className="trust-icon"><ShieldCheck size={16} /></span>{t('hero.trust')}</div>
            <button className="agent-hero-cta" type="button" onClick={() => { document.getElementById('chat-input')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); window.setTimeout(() => document.getElementById('chat-input')?.focus(), 350) }}><span className="agent-cta-icon"><Sparkles size={17} /></span><span>{t('agent.askButton')}</span><ArrowRight size={16} /></button>
          </div>
          <div className="hero-art" role="img" aria-label="Travel inspiration photograph">
            <div className="hero-art-overlay" />
            <div className="hero-art-caption"><span>{t('hero.artLabel')}</span><strong>{request.destination || t('hero.artDefault')}</strong></div>
            <div className="hero-art-stamp"><Sparkles size={15} /> {t('hero.artStamp')}</div>
          </div>
        </section>

        <form className="trip-search" onSubmit={handleSubmit}>
          <div className="search-field destination-field"><label htmlFor="destination"><MapPin size={16} /> {t('search.destination')}</label><input id="destination" list="destination-options" value={request.destination} onChange={(e) => updateDestination(e.target.value)} placeholder={t('search.destinationPlaceholder')} /><datalist id="destination-options">{conciergeService.destinations.map((city) => <option key={city} value={city} />)}</datalist></div>
          <div className="search-field"><label htmlFor="start-date"><CalendarDays size={16} /> {t('search.checkIn')}</label><input id="start-date" type="date" min={today} aria-invalid={dateIssue === 'past'} aria-describedby={dateIssue ? 'date-issue-error' : undefined} value={request.startDate} onChange={(e) => update('startDate', e.target.value)} /></div>
          <div className="search-field"><label htmlFor="end-date"><CalendarDays size={16} /> {t('search.checkOut')}</label><input id="end-date" type="date" min={minEndDate} aria-invalid={dateIssue === 'order'} aria-describedby={dateIssue ? 'date-issue-error' : undefined} value={request.endDate} onChange={(e) => update('endDate', e.target.value)} /></div>
          <div className="search-field guests-field"><label htmlFor="travellers"><Users size={16} /> {t('search.travellers')}</label><div className="guest-stepper"><button type="button" aria-label="Remove traveller" onClick={() => update('travellers', Math.max(1, request.travellers - 1))}><Minus size={14} /></button><span>{request.travellers} {t('search.guests')}</span><button type="button" aria-label="Add traveller" onClick={() => update('travellers', Math.min(12, request.travellers + 1))}><Plus size={14} /></button></div></div>
          <div className="search-field budget-field"><label htmlFor="budget"><Wallet size={15} /> {t('search.budget')}</label><div className="budget-input-row"><input id="budget" inputMode="decimal" value={request.budget} onChange={(e) => update('budget', e.target.value)} aria-label="Budget amount" /><select value={request.currency} onChange={(e) => update('currency', e.target.value)} aria-label="Budget currency">{currencyOptions}</select></div></div>
          <button className="search-submit" type="submit" disabled={loading || !!dateIssue}>{loading ? <span className="spinner" /> : <><span>{t('search.findStay')}</span><ArrowRight size={17} /></>}</button>
          {dateIssue && <p id="date-issue-error" className="date-order-error" role="alert">{dateIssueMessage(dateIssue, 'search')}</p>}
        </form>

        <section className="content-grid stays-only" id="stays-results">
          <div className="left-column">
            <div className="section-heading"><div><div className="eyebrow small-eyebrow">{t('stays.eyebrow')}</div><h2>{t('stays.heading')}</h2></div><button className="text-button" onClick={() => setNotice(t('stays.showingAll'))}>{t('stays.viewAll')} <ArrowRight size={15} /></button></div>
            {conciergeService.isMock && <div className="demo-banner"><span className="demo-dot" /> {t('stays.dataset')} <span>{t('stays.datasetNote')}</span></div>}
            {error && <div className="state-card error-state" role="alert"><CircleHelp size={19} /><div><strong>{t('stays.loadErrorTitle')}</strong><p>{error}</p><button className="text-button" onClick={() => void refreshResults()}>{t('common.tryAgain')} <ArrowRight size={14} /></button></div></div>}
            {loading && hotels.length === 0 && <div className="loading-card"><span className="spinner dark-spinner" /> Finding thoughtful stays…</div>}
            {!error && !loading && hotels.length === 0 && <div className="state-card"><MapPin size={20} /><div><strong>{request.destination ? t('stays.noMatch') : t('stays.whereTo')}</strong><p>{request.destination ? t('stays.noMatchHelp') : t('stays.whereHelp')}</p></div></div>}
            <div className="hotel-list">
              {hotels.map((hotel, index) => <HotelCard key={`${hotel.hotelId}-${hotel.roomTypeId}`} hotel={hotel} featured={index === 0} onSelect={() => { setSelectedHotel(hotel); setHoldMessage('') }} />)}
            </div>
            <button className="assistant-card" onClick={() => document.getElementById('chat-input')?.focus()}>
              <div className="assistant-icon"><Sparkles size={18} /></div><div className="assistant-text"><strong>{t('stays.askSentence')}</strong><span>{t('stays.askSentenceHelp')}</span></div><ArrowUpRight size={18} className="assistant-arrow" />
            </button>
          </div>
        </section>

        <section className="assistant-panel core-agent-panel">
          <div className="panel-top"><div className="assistant-avatar"><Sparkles size={20} /></div><div><strong>{t('agent.title')}</strong><span>{conciergeService.isMock ? t('agent.preview') : t('agent.planStatus')}</span></div><span className="online-pill"><i /> {agentLoading || agentSession?.status === 'executing' ? t('agent.working') : t('agent.ready')}</span></div>
          <section className="agent-trip-brief" aria-label={t('agent.tripBrief')}>
            <div className="agent-brief-heading"><div><span className="mini-label">{t('agent.tripBrief')}</span><p>{t('agent.briefHint')}</p></div><button type="button" className="agent-brief-toggle" disabled={briefEditing && !!dateIssue} onClick={() => setBriefEditing((editing) => !editing)}>{briefEditing ? t('agent.saveBrief') : t('agent.editBrief')}</button></div>
            {briefEditing ? <div className="agent-brief-fields">
              <label htmlFor="agent-destination">{t('search.destination')}<input id="agent-destination" list="destination-options" value={request.destination} onChange={(event) => updateDestination(event.target.value)} placeholder={t('search.destinationPlaceholder')} /></label>
              <label htmlFor="agent-start-date">{t('brief.startDate')}<input id="agent-start-date" type="date" min={today} aria-invalid={dateIssue === 'past'} aria-describedby={dateIssue ? 'agent-date-issue-error' : undefined} value={request.startDate} onChange={(event) => update('startDate', event.target.value)} /></label>
              <label htmlFor="agent-end-date">{t('brief.endDate')}<input id="agent-end-date" type="date" min={minEndDate} aria-invalid={dateIssue === 'order'} aria-describedby={dateIssue ? 'agent-date-issue-error' : undefined} value={request.endDate} onChange={(event) => update('endDate', event.target.value)} /></label>
              {dateIssue && <p id="agent-date-issue-error" className="date-order-error" role="alert">{dateIssueMessage(dateIssue, 'brief')}</p>}
              <label htmlFor="agent-travellers">{t('search.travellers')}<input id="agent-travellers" type="number" min="1" max="12" value={request.travellers} onChange={(event) => update('travellers', Math.min(12, Math.max(1, Number(event.target.value) || 1)))} /></label>
              <label htmlFor="agent-budget">{t('search.budget')}<div className="agent-budget-edit"><input id="agent-budget" inputMode="decimal" value={request.budget} onChange={(event) => update('budget', event.target.value)} /><select aria-label={t('search.budget')} value={request.currency} onChange={(event) => update('currency', event.target.value)}>{currencyOptions}</select></div></label>
              <label className="agent-preferences-edit" htmlFor="agent-preferences">{t('agent.preferences')}<input id="agent-preferences" value={request.preferences} onChange={(event) => update('preferences', event.target.value)} placeholder={t('agent.preferencesPlaceholder')} /></label>
            </div> : <div className="agent-brief-summary"><span>{request.destination || t('agent.noDestination')}</span><span>{formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)}</span><span>{request.travellers} {t('search.guests')}</span><span>{formatMoney(request.budget, request.currency)} {request.currency}</span>{request.preferences && <span className="agent-preference-chip">{request.preferences}</span>}</div>}
          </section>
          <div className="chat-log" role="log" aria-live="polite" aria-label="Conversation with the Yatra trip agent">
            {chatMessages.map((message, index) => <div className={`chat-bubble ${message.role}${message.options ? ' with-options' : ''}`} key={`${message.role}-${index}`}><span>{message.role === 'assistant' ? 'YATRA' : 'YOU'}</span><p>{message.content}</p>
              {message.options && <TripOptions options={message.options} onChoose={(i) => void handleLiveChat(`Option ${i}`)}
                active={index === lastOptionsIndex && agentSession?.status === 'awaiting_input' && !agentLoading} />}
              {message.suggestions && index === chatMessages.length - 1 && agentSession?.status === 'awaiting_input' && <div className="date-suggestions">
                {message.suggestions.map((s) => <button type="button" key={s.reply} title={s.detail} disabled={agentLoading} onClick={() => void handleLiveChat(s.reply)}>{s.label}</button>)}</div>}</div>)}
            {(agentLoading || (agentSession?.status === 'executing' && !stalled)) && <div className="agent-working"><span className="spinner dark-spinner" /> {t('agent.checking')}</div>}
          </div>
          {!conciergeService.isMock && agentSession && <AgentSessionPanel session={agentSession} events={sessionEvents} cart={sessionCart} confirmation={confirmation} booking={booking} verification={verification} stalled={stalled} deciding={deciding} decisionError={decisionError}
            onApprove={() => void handleDecision(true)} onDecline={() => void handleDecision(false)}
            onRefresh={() => { pollStartedAt.current = Date.now(); setStalled(false); void loadSession(agentSession.sessionId).catch(() => undefined) }}
            onVerify={() => void sessionService.verifyAudit(agentSession.sessionId).then(setVerification).catch(() => undefined)} />}
          {conciergeService.isMock && agentSteps.length > 0 && <div className="tool-trace"><span className="mini-label">{t('agent.trace')}</span>{agentSteps.map((step) => <div key={step}><Check size={12} /> {step}</div>)}</div>}
          {conciergeService.isMock && <div className="preview-explainer">{t('agent.previewNote')}</div>}
          <form className="chat-composer" onSubmit={handleChatSubmit}>
            <label className="preferences-label" htmlFor="chat-input">{t('agent.ask')}</label>
            <textarea id="chat-input" rows={4} value={chatDraft} onChange={(e) => setChatDraft(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit() } }} placeholder={t('agent.placeholder')} />
            <div className="chat-composer-footer">
              <span>{t('agent.enter')}</span>
              <div style={{ display: 'inline-flex', gap: '8px', alignItems: 'center' }}>
                <button
                  type="button"
                  className="voice-topbar-button"
                  onClick={() => setShowVoiceModal(true)}
                  title="Speak to Yatra with voice"
                  aria-label="Voice input"
                >
                  <Mic size={14} /> <span>Voice</span>
                </button>
                <button
                  className="send-preferences"
                  type="submit"
                  disabled={agentLoading || agentSession?.status === 'executing' || !chatDraft.trim()}
                >
                  {agentLoading ? t('agent.planning') : t('agent.askButton')} <Send size={14} />
                </button>
              </div>
            </div>
          </form>
          {canReplan && <div className="replan-chips" role="group" aria-label={t('replan.label')}><span>{t('replan.label')}</span>
            {([['replan.cheaper', 'cheaper please'], ['replan.betterHotel', 'a better hotel please'], ['replan.otherHotels', 'show me other hotels'],
              ['replan.morning', 'morning flights please'], ['replan.evening', 'evening flights please']] as const).map(([key, text]) =>
              <button type="button" key={key} disabled={agentLoading} onClick={() => void handleLiveChat(text)}>{t(key)}</button>)}</div>}
          <div className="suggestion-chips" role="group" aria-label="Example trip requests">
            {supportedPromptSuggestions.map(({ label, prompt }) => <button key={prompt} type="button" title={prompt}
              aria-label={`Fill example: ${prompt}`} onClick={() => {
                setChatDraft(prompt)
                const orig = findOrigin(prompt, conciergeService.destinations)
                if (orig) setOriginCity(orig)
              }}>{label}</button>)}
          </div>
        </section>

        {/* Itinerary & Map Side-by-Side Responsive Split (Itinerary Left, Interactive Map Right) */}
        <div className="trip-itinerary-map-split">
          <div className="split-itinerary-pane">
            <StructuredTripPlanCard
              plan={structuredPlan}
              alternatives={planAlternatives}
              selectedOptionId={selectedAlternativeId}
              executionSteps={planExecutionSteps}
              replanning={replanningPlan}
              replanError={replanError}
              selectedActivity={selectedActivity}
              activeDayFilter={activeDayFilter}
              onDayFilterChange={setActiveDayFilter}
              onSelectActivity={(act) => {
                setSelectedActivity(act)
                document.querySelector('.yatra-travel-map-card')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
              }}
              onSelectAlternative={handleSelectAlternative}
              onReplan={handleReplan}
              onRegenerate={handleRegenerate}
              onGenerate={handleGeneratePlan}
              onCompareOptions={handleCompareOptions}
              onOptimizeBudget={() => void handleOptimize('cheaper')}
              onBookTrip={() => {
                if (!currentUser) {
                  setSignInError('Sign in or create an account to continue with booking.')
                  setAuthMode('signin')
                  setSignInOpen(true)
                  return
                }
                if (structuredPlan?.id) {
                  const effectiveId = structuredPlan.id === 'preview_plan' && agentSession?.sessionId
                    ? `session_plan_${agentSession.sessionId}`
                    : structuredPlan.id
                  setReviewingPlan({ id: effectiveId, version: structuredPlan.version || 1 })
                }
              }}
            />
          </div>

          <div className="split-map-pane">
            <TravelMap
              originCity={originCity || structuredPlan?.origin || null}
              destinationCity={request.destination}
              originCoords={originCoords}
              destinationCoords={destinationCoords}
              hotels={hotels}
              selectedHotel={selectedHotel}
              onSelectHotel={(hotel) => {
                setSelectedHotel(hotel)
                setHoldMessage('')
              }}
              activities={mapActivities}
              selectedActivity={selectedActivity}
              onSelectActivity={setSelectedActivity}
              activeDayFilter={activeDayFilter}
              onDayFilterChange={setActiveDayFilter}
              totalDays={structuredPlan?.days?.length ?? 0}
            />
          </div>
        </div>

        {reviewingPlan && (
          <BookingReviewModal
            itineraryId={reviewingPlan.id}
            itineraryVersion={reviewingPlan.version}
            currency={request.currency}
            onClose={() => setReviewingPlan(null)}
            onOpenTripPack={(bkgId) => {
              setReviewingPlan(null)
              setActiveTripPackBookingId(bkgId)
            }}
            onRequireAuth={(mode) => {
              setAuthMode(mode)
              setSignInError('Sign in or create an account to continue with booking.')
              setSignInOpen(true)
            }}
          />
        )}
        {activeTripPackBookingId && (
          <TripPackModal
            bookingId={activeTripPackBookingId}
            onClose={() => setActiveTripPackBookingId(null)}
          />
        )}

        {/* Intelligent Travel Comparison & Trade-Offs (Phase 3) */}
        <TravelOptionsComparisonCard
          options={comparisonOptions}
          summary={comparisonSummary}
          tradeOffs={comparisonTradeOffs}
          currency={request.currency || 'INR'}
          onApplyOption={handleApplyTravelOption}
          onOptimize={handleOptimize}
          optimizing={comparingOptions}
          pendingDiff={pendingPlanDiff}
          onConfirmDiff={handleConfirmDiff}
          onDismissDiff={handleDismissDiff}
        />

        {/* Destination Explorer (Phase 4) */}
        <DestinationExplorerCard
          key={`dest-${currentUser?.userId || 'guest'}`}
          destination={request.destination || 'Jaipur'}
          itineraryId={structuredPlan?.id && structuredPlan.id !== 'preview_plan' ? structuredPlan.id : undefined}
          onSelectCoordinates={handleSelectExplorerCoords}
          onActivityAdded={handleRefreshActivePlan}
        />

        {/* Rich Hotel Explorer (Phase 4) */}
        <HotelExplorerCard
          key={`hotel-${currentUser?.userId || 'guest'}`}
          destination={request.destination || 'Jaipur'}
          startDate={request.startDate}
          endDate={request.endDate}
          travellers={request.travellers}
          itineraryId={structuredPlan?.id && structuredPlan.id !== 'preview_plan' ? structuredPlan.id : undefined}
          onSelectCoordinates={handleSelectExplorerCoords}
          onHotelSelected={() => {
            void handleRefreshActivePlan()
            setNotice('Hotel stay updated successfully.')
          }}
        />

        {/* Budget, day-by-day plan and XR sit under the agent that fills them. */}
        <section className="trip-overview-row">
          <BudgetCard budget={shownBudget} remaining={remaining} live={!conciergeService.isMock} capSource={agentSession?.capSource} />

          {conciergeService.isMock ? <section className="itinerary-card">
            <div className="itinerary-heading"><div><span className="mini-label">{t('itinerary.eyebrow')}</span><h3>{t('itinerary.heading')}</h3></div><button className="round-arrow" aria-label={t('itinerary.view')} onClick={() => setNotice(t('itinerary.editingSoon'))}><ArrowUpRight size={17} /></button></div>
            {itinerary.length ? <><div className="itinerary-date"><span className="date-number">17</span><span><strong>{new Intl.DateTimeFormat(language.tag, { weekday: 'long' }).format(itinerarySampleDate)}</strong><small>{new Intl.DateTimeFormat(language.tag, { month: 'long' }).format(itinerarySampleDate)} · {t('itinerary.dayTwo')}</small></span><span className="sun-symbol"><Sun size={15} /></span></div><div className="timeline">{itinerary.map((stop) => <TimelineStop key={stop.id} stop={stop} />)}</div><button className="text-button itinerary-more" onClick={() => setNotice(t('itinerary.editingSoon'))}>{t('itinerary.fullDay')} <ArrowRight size={14} /></button></> : <p className="empty-panel-copy">{t('itinerary.empty')}</p>}
          </section> : <ItineraryCard cart={sessionCart} />}

          <XRCard destination={request.destination || 'Jaipur'} imageUrl={destinationPhoto(request.destination || 'Jaipur')} />
        </section>

        <FlightSearchPage onSelectFlight={(flight: FlightOption) => {
          setOriginCity(flight.originCity)
          if (flight.destinationCity) updateDestination(flight.destinationCity)
          setNotice(t('flight.selectedNotice').replace('{airline}', flight.airlineName).replace('{number}', flight.flightNumber))
        }} />
        <ExplorePage request={request} onAskYatra={(prompt) => { setChatDraft(prompt); document.querySelector('.assistant-panel')?.scrollIntoView({ behavior: 'smooth', block: 'center' }); window.setTimeout(() => document.getElementById('chat-input')?.focus(), 450) }} onPlanDestination={(city) => { updateDestination(city); document.getElementById('plan')?.scrollIntoView({ behavior: 'smooth', block: 'start' }); setNotice(t('explore.selectedNotice').replace('{city}', city)) }} />
        <MyTripsPage signedIn={!!currentUser} onResume={(trip) => void resumeTrip(trip)}
          refreshKey={`${currentUser?.userId ?? ''}:${agentSession?.sessionId ?? ''}:${agentSession?.status ?? ''}:${booking ? 'booked' : ''}`}
          onPlanNew={(city) => { if (city) updateDestination(city); document.getElementById('plan')?.scrollIntoView({ behavior: 'smooth', block: 'start' }) }} />
        <footer className="footer">
          <div className="footer-left">
            <span>© 2026 Yatra Saathi.</span>
            <span className="dot-sep">·</span>
            <span className="footer-tagline-wrap">{t('footer.tagline')} <Heart size={13} className="footer-heart" /></span>
          </div>
          <div className="footer-links">
            <a href="/privacy" onClick={(e) => { e.preventDefault(); navigate('/privacy') }}>Privacy Policy</a>
            <span className="dot-sep">·</span>
            <a href="/terms" onClick={(e) => { e.preventDefault(); navigate('/terms') }}>Terms of Service</a>
          </div>
        </footer>
      </main>

      {selectedHotel && !conciergeService.isMock && <StayDetailModal hotel={selectedHotel} request={request} onClose={closeStay} onPlan={() => planStay(selectedHotel)} />}
      {selectedHotel && conciergeService.isMock && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setSelectedHotel(null) }}><section className="confirm-modal" role="dialog" aria-modal="true" aria-labelledby="confirm-title"><button className="modal-close" aria-label="Close" onClick={() => setSelectedHotel(null)}><X size={19} /></button><div className="modal-icon"><ShieldCheck size={21} /></div><span className="mini-label">{t('modal.review')}</span><h2 id="confirm-title">{t('modal.title')}</h2><p className="modal-hotel-name">{selectedHotel.name} · {selectedHotel.roomName}</p><div className="modal-summary"><span><MapPin size={15} /> {selectedHotel.city}</span><span><CalendarDays size={15} /> {formatShortDate(request.startDate, language.tag)} – {formatShortDate(request.endDate, language.tag)}</span><strong>{formatMoney(selectedHotel.price, selectedHotel.currency)} <small>/ stay</small></strong></div><p className="modal-disclaimer">Review the details with your travel group. This preview will not reserve a room or charge you.</p>{holdMessage && <div className="modal-result" role="status">{holdMessage}</div>}<button className="modal-primary" onClick={() => void handleHold()} disabled={holding}>{holding ? 'Checking…' : t('modal.bookingOptions')} <ArrowRight size={16} /></button><button className="modal-secondary" onClick={() => setSelectedHotel(null)}>{t('modal.keepExploring')}</button></section></div>}

      {signInOpen && (
        <div
          className="modal-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget && !signingIn) setSignInOpen(false)
          }}
        >
          <section
            className="confirm-modal signin-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="signin-title"
          >
            <button
              className="modal-close"
              aria-label="Close"
              onClick={() => setSignInOpen(false)}
            >
              <X size={19} />
            </button>
            <div className="modal-icon">
              {authMode === 'signin' ? <UserRound size={20} /> : <UserPlus size={20} />}
            </div>
            <span className="mini-label">
              {authMode === 'signin' ? t('signin.welcome') : 'GET STARTED'}
            </span>
            <h2 id="signin-title">
              {authMode === 'signin' ? 'Welcome back' : 'Create your Yatra Saathi account'}
            </h2>
            <p className="signin-subtitle">
              {authMode === 'signin'
                ? 'Sign in with your username or email address and password.'
                : 'Join Yatra Saathi for intelligent trip planning, budget tracking, and real-time alerts.'}
            </p>

            <div className="auth-mode-switch" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={authMode === 'signin'}
                className={authMode === 'signin' ? 'selected' : ''}
                onClick={() => {
                  setAuthMode('signin')
                  setSignInError('')
                  setForgotPasswordNote('')
                }}
              >
                Sign in
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={authMode === 'register'}
                className={authMode === 'register' ? 'selected' : ''}
                onClick={() => {
                  setAuthMode('register')
                  setSignInError('')
                  setForgotPasswordNote('')
                }}
              >
                Create account
              </button>
            </div>

            <form className="signin-form" onSubmit={(event) => void handleAuthSubmit(event)}>
              {authMode === 'signin' ? (
                <>
                  <label htmlFor="signin-identifier">
                    <Mail size={14} /> Email or username
                  </label>
                  <input
                    id="signin-identifier"
                    name="identifier"
                    type="text"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                    maxLength={320}
                    placeholder="e.g. usr_demo0001 or you@example.com"
                  />

                  <label htmlFor="signin-password">
                    <Lock size={14} /> Password
                  </label>
                  <div className="pw-input-wrapper">
                    <input
                      id="signin-password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="current-password"
                      required
                      maxLength={128}
                      placeholder="••••••••"
                    />
                    <button
                      type="button"
                      className="pw-toggle-btn"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>

                  <button
                    type="button"
                    className="auth-forgot-link"
                    onClick={() => {
                      setForgotPasswordNote(
                        'Password reset email delivery is not configured in the current local/demo environment.'
                      )
                    }}
                  >
                    Forgot password?
                  </button>

                  {forgotPasswordNote && (
                    <div className="auth-info-note" role="note">
                      {forgotPasswordNote}
                    </div>
                  )}
                </>
              ) : (
                <>
                  <label htmlFor="register-full-name">
                    <UserRound size={14} /> Full name
                  </label>
                  <input
                    id="register-full-name"
                    name="fullName"
                    type="text"
                    autoComplete="name"
                    required
                    maxLength={100}
                    placeholder="e.g. Sharath Kumar"
                  />

                  <label htmlFor="register-username">
                    <IdCard size={14} /> Username
                  </label>
                  <input
                    id="register-username"
                    name="username"
                    type="text"
                    autoComplete="username"
                    autoCapitalize="none"
                    spellCheck={false}
                    required
                    minLength={3}
                    maxLength={30}
                    placeholder="e.g. sharath_travels"
                  />

                  <label htmlFor="register-email">
                    <Mail size={14} /> Email address
                  </label>
                  <input
                    id="register-email"
                    name="email"
                    type="email"
                    autoComplete="email"
                    required
                    maxLength={320}
                    placeholder="you@example.com"
                  />

                  <label htmlFor="register-password">
                    <Lock size={14} /> Password
                  </label>
                  <div className="pw-input-wrapper">
                    <input
                      id="register-password"
                      name="password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      required
                      minLength={8}
                      maxLength={128}
                      placeholder="At least 8 characters"
                    />
                    <button
                      type="button"
                      className="pw-toggle-btn"
                      aria-label={showPassword ? 'Hide password' : 'Show password'}
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>

                  <label htmlFor="register-confirm-password">
                    <Lock size={14} /> Confirm password
                  </label>
                  <div className="pw-input-wrapper">
                    <input
                      id="register-confirm-password"
                      name="confirmPassword"
                      type={showConfirmPassword ? 'text' : 'password'}
                      autoComplete="new-password"
                      required
                      minLength={8}
                      maxLength={128}
                      placeholder="Confirm your password"
                    />
                    <button
                      type="button"
                      className="pw-toggle-btn"
                      aria-label={showConfirmPassword ? 'Hide password' : 'Show password'}
                      onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                    >
                      {showConfirmPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>

                  <label className="auth-checkbox-label" htmlFor="register-terms">
                    <input id="register-terms" name="agreeTerms" type="checkbox" />
                    <span>
                      I agree to the Yatra Saathi{' '}
                      <a
                        href="/terms"
                        onClick={(e) => {
                          e.preventDefault()
                          setSignInOpen(false)
                          navigate('/terms')
                        }}
                      >
                        Terms of Service
                      </a>{' '}
                      &amp;{' '}
                      <a
                        href="/privacy"
                        onClick={(e) => {
                          e.preventDefault()
                          setSignInOpen(false)
                          navigate('/privacy')
                        }}
                      >
                        Privacy Policy
                      </a>
                    </span>
                  </label>
                </>
              )}

              {signInError && (
                <div className="modal-result signin-error" role="alert">
                  {signInError}
                </div>
              )}

              <button className="modal-primary" type="submit" disabled={signingIn}>
                {signingIn ? (
                  <span className="spinner" />
                ) : (
                  <>
                    {authMode === 'signin' ? 'Sign in' : 'Create account'} <ArrowRight size={15} />
                  </>
                )}
              </button>
            </form>

            <div className="auth-switch-row">
              {authMode === 'signin' ? (
                <span>
                  Don't have an account?{' '}
                  <button
                    type="button"
                    className="auth-switch-link"
                    onClick={() => {
                      setAuthMode('register')
                      setSignInError('')
                      setForgotPasswordNote('')
                    }}
                  >
                    Create an account
                  </button>
                </span>
              ) : (
                <span>
                  Already have an account?{' '}
                  <button
                    type="button"
                    className="auth-switch-link"
                    onClick={() => {
                      setAuthMode('signin')
                      setSignInError('')
                      setForgotPasswordNote('')
                    }}
                  >
                    Sign in
                  </button>
                </span>
              )}
            </div>

            <div className="signin-divider">
              <span />
              {t('auth.or')}
              <span />
            </div>

            <button
              className="modal-secondary"
              onClick={() => {
                setSignInOpen(false)
                setNotice(t('signin.guest'))
              }}
            >
              {t('signin.continue')}
            </button>

            <p className="signin-footnote">
              {authMode === 'signin'
                ? 'Your credentials are authenticated directly against Yatra Saathi with Argon2id hashing.'
                : 'Passphrases are one-way hashed with Argon2id. Yatra Saathi never stores plaintext credentials.'}
            </p>
          </section>
        </div>
      )}
      {notificationsOpen && <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setNotificationsOpen(false) }}><section className="confirm-modal notifications-modal" role="dialog" aria-modal="true" aria-labelledby="notifications-title"><button className="modal-close" aria-label={t('notifications.close')} onClick={() => setNotificationsOpen(false)}><X size={19} /></button><div className="modal-icon"><Bell size={20} /></div><span className="mini-label">{t('notifications.eyebrow')}</span><h2 id="notifications-title">{t('notifications.title')}</h2><p className="signin-subtitle">{t('notifications.subtitle')}</p><div className="notification-options">{([{ key: 'tripUpdates', label: 'notifications.tripUpdates' }, { key: 'bookingUpdates', label: 'notifications.bookingUpdates' }, { key: 'priceChanges', label: 'notifications.priceChanges' }, { key: 'itineraryReminders', label: 'notifications.itineraryReminders' }, { key: 'agentSuggestions', label: 'notifications.agentSuggestions' }] as const).map(({ key, label }) => <label className="notification-option" key={key}><span>{t(label)}</span><input type="checkbox" checked={notificationPreferences[key]} onChange={(event) => setNotificationPreferences((current) => ({ ...current, [key]: event.target.checked }))} /></label>)}</div><PushPanel prefs={notificationPreferences} signedIn={!!currentUser} /><p className="notification-local-note">{t('notifications.localNote')}</p><button className="modal-primary" onClick={() => setNotificationsOpen(false)}>{t('notifications.save')}</button></section></div>}
      {showPreferencesModal && (
        <PreferencesPanel
          isOpen={showPreferencesModal}
          onClose={() => setShowPreferencesModal(false)}
        />
      )}

      {showVoiceModal && (
        <VoiceAssistantModal
          isOpen={showVoiceModal}
          onClose={() => setShowVoiceModal(false)}
          currentLanguage={language.tag}
          onExecuteAction={(voiceText) => {
            setChatDraft(voiceText)
            if (!conciergeService.isMock) {
              void handleLiveChat(voiceText)
            } else {
              document.getElementById('chat-input')?.focus()
            }
          }}
        />
      )}

      {showNotificationCenter && (
        <NotificationCenterModal
          isOpen={showNotificationCenter}
          onClose={() => {
            setShowNotificationCenter(false)
            void refreshUnreadCount()
          }}
          currentUserId={currentUser?.userId}
          onOpenTrip={() => {
            document.getElementById('my-trips')?.scrollIntoView({ behavior: 'smooth' })
          }}
          onOpenBooking={(bkgId) => {
            setActiveTripPackBookingId(bkgId)
          }}
        />
      )}

      {showEmergencyModal && (
        <EmergencyAssistanceModal
          isOpen={showEmergencyModal}
          onClose={() => setShowEmergencyModal(false)}
          currentTripId={activeTripPackBookingId || undefined}
        />
      )}
    </div>
  )
}

function HotelCard({ hotel, featured, onSelect }: { hotel: HotelOption; featured: boolean; onSelect: () => void }) {
  const { t } = useLanguage()
  return <article className={`hotel-card ${featured ? 'featured-hotel' : ''}`}>
    <div className="hotel-image-wrap"><img src={hotel.imageUrl} alt={t('stay.photoAlt').replace('{city}', hotel.city).replace('{hotel}', hotel.name)} loading="lazy" /><span className="image-location"><MapPin size={12} /> {hotel.city}</span>{featured && <span className="pick-badge"><Sparkles size={12} /> {t('stays.lowestTotal')}</span>}</div>
    <div className="hotel-info"><div className="hotel-title-row"><div><div className="hotel-kicker">{hotel.country.toUpperCase()} <span>·</span> {hotel.roomName}</div><h3>{hotel.name}</h3></div><button className="save-button" aria-label={`${t('stays.save')}: ${hotel.name}`} title={t('stays.save')} onClick={(e) => { e.currentTarget.classList.toggle('saved'); e.currentTarget.setAttribute('aria-pressed', String(e.currentTarget.classList.contains('saved'))) }}><Heart size={15} /></button></div>
      <p className="hotel-description">{hotel.description}</p><div className="hotel-tags">{hotel.tags.map((tag) => <span key={tag}>{tag}</span>)}</div>
      <div className="hotel-bottom"><div><strong>{formatMoney(hotel.price, hotel.currency)}</strong><span>{t('stays.nights').startsWith('nights') ? `for ${hotel.nights} ${t('stays.nights')}` : `${hotel.nights} ${t('stays.nights')}`}</span><small>{t('stays.units').replace('{count}', String(hotel.availableUnits))}</small>{hotel.localPrice && hotel.localCurrency && hotel.localCurrency !== hotel.currency && <small className="local-price">≈ {formatMoney(hotel.localPrice, hotel.localCurrency)} {t('price.local')}</small>}</div><button className="choose-button" onClick={onSelect}>{t('stays.viewStay')} <ArrowRight size={15} /></button></div>
    </div>
  </article>
}

function BudgetCard({ budget, remaining, live = false, capSource }: { budget: BudgetSummary | null; remaining: string; live?: boolean; capSource?: string }) {
  const { t } = useLanguage()
  const statusLabel = live ? t('budget.live') : t('budget.preview')
  if (!budget) return <section className="budget-card budget-empty"><div className="budget-header"><span className="budget-icon"><Wallet size={17} /></span><div><span className="mini-label">{t('budget.title')}</span><h3>{t('budget.overview')}</h3></div><span className="budget-status"><span /> {statusLabel}</span></div><p>{live ? t('budget.liveEmpty') : t('stays.budgetEmpty')}</p><div className="budget-empty-hint"><Sparkles size={15} /><span>{t('stays.askSentence')}</span></div></section>
  const totalMinor = decimalToMinorUnits(budget.total)
  const plannedMinor = decimalToMinorUnits(budget.planned)
  const committedMinor = decimalToMinorUnits(budget.committed)
  const usedMinor = committedMinor + plannedMinor
  const committedWidth = totalMinor <= 0n ? 0 : Math.min(100, Number((committedMinor * 10000n) / totalMinor) / 100)
  const plannedWidth = totalMinor <= 0n ? 0 : Math.min(100 - committedWidth, Number((plannedMinor * 10000n) / totalMinor) / 100)
  const progress = totalMinor <= 0n ? 0 : Math.min(100, Math.max(0, Number((usedMinor * 10000n) / totalMinor) / 100))
  return <section className="budget-card"><div className="budget-header"><span className="budget-icon"><Wallet size={17} /></span><div><span className="mini-label">{t('budget.title')}</span><h3>{t('budget.overview')}</h3></div><span className="budget-status"><span /> {statusLabel}</span></div><div className="budget-total"><span>{t('budget.allowance')}</span><strong>{formatMoney(budget.total, budget.currency)}</strong></div><div className="budget-meter-heading"><span>{t('budget.heading')}</span><strong>{progress.toFixed(0)}%</strong></div><div className="budget-track" role="img" aria-label={`${progress.toFixed(0)}% of trip budget planned or committed`}><span className="budget-committed-fill" style={{ width: `${committedWidth}%` }} /><span className="budget-planned-fill" style={{ left: `${committedWidth}%`, width: `${plannedWidth}%` }} /></div><div className="budget-legend"><div><i className="committed-dot" /> <span>{t('budget.committed')}</span><strong>{formatMoney(budget.committed, budget.currency)}</strong></div><div><i className="planned-dot" /> <span>{t('budget.planned')}</span><strong>{formatMoney(budget.planned, budget.currency)}</strong></div></div><div className="budget-remaining"><div><span>{t('budget.remaining')}</span><small>{t('budget.allowance')}</small></div><strong>{formatMoney(remaining, budget.currency)}</strong></div><div className="budget-note"><Check size={13} /> {live ? t(capSource === 'budget' ? 'budget.capFromTrip' : 'budget.capFromSession') : <>{t('budget.preview')} <span>· backend will provide live totals</span></>}</div></section>
}

// Live mode: the day-by-day plan comes from the flights and hotel nights in the agent's cart.
function ItineraryCard({ cart }: { cart: Cart | null }) {
  const { language, t } = useLanguage()
  const [expanded, setExpanded] = useState(false)
  const days = useMemo(() => itineraryFromCart(cart, t), [cart, t])
  const shown = expanded ? days : days.slice(0, 2)
  return <section className="itinerary-card">
    <div className="itinerary-heading"><div><span className="mini-label">{t('itinerary.eyebrow')}</span><h3>{t('itinerary.heading')}</h3></div></div>
    {days.length ? <>
      <p className="itinerary-source">{t('itinerary.fromCart')}</p>
      {shown.map((day, index) => {
        const date = new Date(`${day.date}T12:00:00`)
        return <div className="itinerary-day" key={day.date}>
          <div className="itinerary-date"><span className="date-number">{date.getDate()}</span><span><strong>{new Intl.DateTimeFormat(language.tag, { weekday: 'long' }).format(date)}</strong><small>{new Intl.DateTimeFormat(language.tag, { month: 'long' }).format(date)} · {t('itinerary.day').replace('{n}', String(days.indexOf(day) + 1))}</small></span>{index === 0 && !expanded && <span className="sun-symbol"><Sun size={15} /></span>}</div>
          <div className="timeline">{day.stops.map((stop) => <TimelineStop key={stop.id} stop={stop} />)}</div>
        </div>
      })}
      {days.length > 2 && <button className="text-button itinerary-more" onClick={() => setExpanded(!expanded)}>{expanded ? t('itinerary.showLess') : t('itinerary.showAll').replace('{count}', String(days.length))} <ArrowRight size={14} /></button>}
    </> : <p className="empty-panel-copy">{t('itinerary.emptyLive')}</p>}
  </section>
}

function TimelineStop({ stop }: { stop: ItineraryStop }) {
  const renderIcon = () => {
    switch (stop.category) {
      case 'food': return <Utensils size={12} />
      case 'nature': return <Trees size={12} />
      case 'stay': return <Hotel size={12} />
      case 'flight': return <Plane size={12} />
      default: return <Sparkles size={12} />
    }
  }
  return <div className="timeline-stop"><div className={`timeline-icon ${stop.category}`}>{renderIcon()}</div><div className="timeline-time">{stop.time}</div><div className="timeline-copy"><strong>{stop.title}</strong><span>{stop.detail}</span></div></div>
}

function XRCard({ destination, imageUrl }: { destination: string; imageUrl: string }) {
  const { t } = useLanguage()
  const [open, setOpen] = useState(false)
  return <>
    <section className="xr-card"><div className="xr-art" style={{ backgroundImage: `linear-gradient(90deg,#172e27bb,#172e2730),url("${imageUrl}")`, backgroundSize: 'cover', backgroundPosition: 'center' }}><span className="xr-orbit orbit-one" /><span className="xr-orbit orbit-two" /><span className="xr-label">{t('xr.label')}</span><div className="xr-object"><Maximize2 size={36} /></div><span className="xr-caption">{t('xr.caption')}</span></div><button className="xr-action" onClick={() => setOpen(true)}>{t('xr.button')} <ArrowUpRight size={15} /></button><span className="xr-pending">{t('xr.ready')}</span></section>
    {open && <Suspense fallback={<div className="modal-backdrop xr-backdrop"><span className="spinner" /></div>}><XRViewer city={destination} photoUrl={imageUrl} onClose={() => setOpen(false)} /></Suspense>}
  </>
}
