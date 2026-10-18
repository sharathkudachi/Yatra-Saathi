import catalog from '../mocks/hotelCatalog.json'
import { demoBudget, demoItinerary } from '../mocks/demoData'
import type { AgentTurnResponse, BudgetSummary, HotelOption, HoldResult, ItineraryStop, TripRequest } from '../types/travel'
import { apiRequest } from './apiClient'
import { decimalToMinorUnits, sumMoney } from '../utils/format'

const useMock = import.meta.env.VITE_USE_MOCK_API !== 'false'
const cityMap = catalog.cities as Record<string, { name: string; countryCode: string; defaultCurrency: string }>
const photoSet = [
  'https://images.unsplash.com/photo-1566073771259-6a8506099945?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1542314831-068cd1dbfeeb?auto=format&fit=crop&w=1000&q=85',
  'https://images.unsplash.com/photo-1564013799919-ab600027ffc6?auto=format&fit=crop&w=1000&q=85',
]
const destinationPhotos: Record<string, string> = {
  Jaipur: 'photo-1599661046827-dacff0c0f09a', Udaipur: 'photo-1590759668628-0f4a1c6b35d3', Jodhpur: 'photo-1512343879784-a960bf40e7f2',
  Agra: 'photo-1564507592333-c60657eea523', Mumbai: 'photo-1570168007204-dfb528c6958f', Panaji: 'photo-1512343879784-a960bf40e7f2',
  NewDelhi: 'photo-1587474260584-136574528ed5', Bangkok: 'photo-1508009603885-50cf7c579365', Singapore: 'photo-1525625293386-3f8f99389edd',
  Bali: 'photo-1537996194471-e657df975ab4', Kyoto: 'photo-1493976040374-85c8e12f0c0e', Dubai: 'photo-1512453979798-5ea266f8880c',
  Kathmandu: 'photo-1544735716-392fe2489ffa', Colombo: 'photo-1740812517101-fee71e001ebc',
}
export function destinationPhoto(city: string) {
  const key = city.replaceAll(' ', '')
  const photo = destinationPhotos[key] ?? photoSet[Array.from(city).reduce((sum, char) => sum + char.charCodeAt(0), 0) % photoSet.length].match(/photo-[^?]+/)?.[0]
  return `https://images.unsplash.com/${photo}?auto=format&fit=crop&w=900&q=82`
}

type InventoryRow = { id: string; date: string; price: string; currency: string; remaining: number }
type CatalogRoom = { id: string; name: string; maxOccupancy: number; currency: string; inventory: InventoryRow[] }
type CatalogHotel = { id: string; cityId: string; name: string; description: string; propertyType: string; starRating: number; rooms: CatalogRoom[] }
const hotelsCatalog = catalog.hotels as CatalogHotel[]
const destinationAliases: Record<string, string> = { goa: 'Panaji', delhi: 'New Delhi' }

function canonicalCityName(name: string) {
  return Object.values(cityMap).find((city) => normalize(city.name) === normalize(name))?.name
    ?? destinationAliases[normalize(name)]
    ?? name
}

export const conciergeService = {
  get isMock() { return useMock },
  get destinations() { return Object.values(cityMap).map((city) => city.name).sort((a, b) => a.localeCompare(b)) },
  async exploreDestinations(request: TripRequest) {
    return Object.values(cityMap).sort((a, b) => a.name.localeCompare(b.name)).map((city) => {
      const results = searchDataset({ ...request, destination: city.name, currency: city.defaultCurrency, budget: '999999999999.99' })
      return { name: city.name, countryCode: city.countryCode, currency: city.defaultCurrency, hotelCount: results.length, fromPrice: results[0]?.price ?? null, imageUrl: destinationPhoto(city.name) }
    })
  },
  currencyForDestination(name: string) {
    const canonical = canonicalCityName(name)
    const city = Object.values(cityMap).find((entry) => normalize(entry.name) === normalize(canonical))
    return city?.defaultCurrency ?? null
  },

  async searchHotels(request: TripRequest): Promise<HotelOption[]> {
    if (useMock) {
      await pause(350)
      return searchDataset(request)
    }
    return apiRequest<HotelOption[]>('/api/search/hotels', { method: 'POST', body: JSON.stringify(request) })
  },

  async sendAgentTurn(message: string, currentRequest: TripRequest, goalLanguage = 'en-IN'): Promise<AgentTurnResponse> {
    if (!useMock) {
      return apiRequest<AgentTurnResponse>('/api/agent/turn', {
        method: 'POST', body: JSON.stringify({ message, goalLanguage, tripRequest: currentRequest }),
      })
    }

    await pause(650)
    let parsed = parsePreviewRequest(message, currentRequest)
    const explicitlyNamedCity = Object.values(cityMap).some((city) => new RegExp(`(^|[^a-z])${escapeRegExp(normalize(city.name))}([^a-z]|$)`).test(normalize(message)))
    const recommendationIntent = !explicitlyNamedCity && /(\b(recommend|recommendation|where|surprise|ideas|anywhere|choose)\b|सुझाव|सुझाएँ|चुनने|कहाँ|பரிந்துரைக்கவும்|பரிந்துரை|సూచించండి|ఎంచుకోవడంలో|সাজেস্ট করুন|গন্তব্য বেছে|सुचवा|ठिकाण निवडण्यात)/iu.test(message)
    let recommendedCity = ''
    if (recommendationIntent) {
      const matches = Object.values(cityMap).filter((city) => city.defaultCurrency === parsed.currency).flatMap((city) => {
        const options = searchDataset({ ...parsed, destination: city.name, budget: parsed.budget || '25000.00' })
        return options.length ? [{ city: city.name, price: options[0].price }] : []
      }).sort((a, b) => decimalToMinorUnits(a.price) < decimalToMinorUnits(b.price) ? -1 : 1)
      recommendedCity = matches[0]?.city ?? ''
      if (recommendedCity) parsed = { ...parsed, destination: recommendedCity }
    }
    if (!parsed.destination) {
      return {
        assistantMessage: previewAgentReply(goalLanguage, recommendationIntent ? 'no-recommendation' : 'need-destination', parsed),
        tripRequest: parsed,
        toolSteps: previewAgentSteps(goalLanguage, parsed, recommendationIntent, false),
        hotels: [], budget: null, itinerary: [],
      }
    }

    const results = searchDataset(parsed)
    const match = isSeededJaipurTrip(parsed)
    const localizedResponse = previewAgentReply(goalLanguage, recommendationIntent && recommendedCity && results.length ? 'recommendation' : results.length ? 'results' : 'no-results', parsed, recommendedCity, results.length)

    return {
      assistantMessage: localizedResponse,
      tripRequest: parsed,
      toolSteps: previewAgentSteps(goalLanguage, parsed, recommendationIntent, true),
      hotels: results,
      budget: match ? demoBudget : null,
      itinerary: match ? demoItinerary : [],
    }
  },

  async getItinerary(request: TripRequest): Promise<ItineraryStop[]> {
    if (useMock) return isSeededJaipurTrip(request) ? demoItinerary : []
    return apiRequest<ItineraryStop[]>('/api/itinerary', {
      method: 'POST', body: JSON.stringify({ tripRequest: request }),
    })
  },

  async getBudget(request: TripRequest): Promise<BudgetSummary | null> {
    if (useMock) return isSeededJaipurTrip(request) ? demoBudget : null
    return apiRequest<BudgetSummary | null>('/api/budget', {
      method: 'POST', body: JSON.stringify({ tripRequest: request }),
    })
  },

  async createHold(hotelId: string): Promise<HoldResult> {
    if (useMock) {
      await pause(300)
      return { status: 'mock_only', message: `Preview only: no hold or booking was created for ${hotelId}. Connect the backend to reserve inventory.` }
    }
    return apiRequest<HoldResult>('/api/holds', { method: 'POST', body: JSON.stringify({ hotelId }) })
  },
}

function searchDataset(request: TripRequest): HotelOption[] {
  if (!request.destination.trim() || !request.startDate || !request.endDate || request.travellers < 1) return []
  const canonicalDestination = canonicalCityName(request.destination)
  const city = Object.values(cityMap).find((entry) => normalize(entry.name) === normalize(canonicalDestination))
  if (!city) return []
  const cityId = Object.keys(cityMap).find((id) => cityMap[id] === city)
  if (!cityId) return []
  const dates = stayDates(request.startDate, request.endDate)
  if (!dates.length) return []
  const budget = safeMinorUnits(request.budget)
  if (budget === null) return []

  const options: HotelOption[] = []
  hotelsCatalog.filter((hotel) => hotel.cityId === cityId).forEach((hotel, hotelIndex) => {
    hotel.rooms.forEach((room) => {
      if (room.maxOccupancy < request.travellers || room.currency !== request.currency) return
      const nightlyRows = dates.map((date) => room.inventory.find((row) => row.date === date && row.remaining >= 1))
      if (nightlyRows.some((row) => !row)) return
      const rows = nightlyRows as InventoryRow[]
      const totalPrice = sumMoney(rows.map((row) => row.price))
      if (decimalToMinorUnits(totalPrice) > budget) return
      const cityInfo = cityMap[hotel.cityId]
      options.push({
        hotelId: hotel.id,
        roomTypeId: room.id,
        inventoryIds: rows.map((row) => row.id),
        maxOccupancy: room.maxOccupancy,
        name: hotel.name,
        city: city.name,
        country: cityInfo.countryCode,
        description: hotel.description,
        imageUrl: photoSet[hotelIndex % photoSet.length],
        roomName: room.name,
        price: totalPrice,
        currency: room.currency,
        nights: rows.length,
        availableUnits: Math.min(...rows.map((row) => row.remaining)),
        tags: [hotel.propertyType.replaceAll('_', ' '), `${hotel.starRating} star`],
      })
    })
  })
  return options.sort((a, b) => {
    const left = decimalToMinorUnits(a.price); const right = decimalToMinorUnits(b.price)
    return left < right ? -1 : left > right ? 1 : 0
  }).slice(0, 12)
}

function parsePreviewRequest(message: string, current: TripRequest): TripRequest {
  const normalizedMessage = normalize(message)
  const cityEntry = Object.values(cityMap).sort((a, b) => b.name.length - a.name.length)
    .find((city) => new RegExp(`(^|[^a-z])${escapeRegExp(normalize(city.name))}([^a-z]|$)`).test(normalizedMessage))
  const aliasEntry = Object.entries(destinationAliases).find(([alias]) => new RegExp(`(^|[^a-z])${escapeRegExp(alias)}([^a-z]|$)`).test(normalizedMessage))
  const aliasedCity = aliasEntry ? Object.values(cityMap).find((city) => normalize(city.name) === normalize(aliasEntry[1])) : undefined
  const destination = cityEntry?.name ?? aliasedCity?.name ?? current.destination
  let budget = current.budget
  let currency = (cityEntry ?? aliasedCity)?.defaultCurrency ?? current.currency
  const budgetMention = message.match(/(?:under|below|within|budget(?:\s+of)?|less\s+than)\s*(₹|\$|€|£)?\s*([\d,]+(?:\.\d{1,2})?)/i)
  if (budgetMention) {
    budget = budgetMention[2].replaceAll(',', '')
    if (budgetMention[1] === '$') currency = 'USD'
    if (budgetMention[1] === '€') currency = 'EUR'
    if (budgetMention[1] === '£') currency = 'GBP'
    if (budgetMention[1] === '₹') currency = 'INR'
  }
  const guestMention = message.match(/(?:for|with)\s+(\d+)\s+(?:travellers?|travelers?|people|guests?|persons?)/i)
  const isoDates = message.match(/\b\d{4}-\d{2}-\d{2}\b/g)
  const dates = isoDates && isoDates.length >= 2 ? isoDates : null
  return {
    ...current,
    destination,
    currency,
    budget,
    travellers: guestMention ? Math.min(12, Math.max(1, Number(guestMention[1]))) : current.travellers,
    startDate: dates?.[0] ?? current.startDate,
    endDate: dates?.[1] ?? current.endDate,
    preferences: message,
  }
}

function isSeededJaipurTrip(request: TripRequest) {
  return normalize(request.destination) === 'jaipur' && request.startDate === '2026-11-16'
    && request.endDate === '2026-11-20' && request.travellers === 1
    && request.currency === 'INR' && request.budget === '16000.00'
}

function stayDates(checkIn: string, checkOut: string) {
  const start = Date.parse(`${checkIn}T00:00:00Z`)
  const end = Date.parse(`${checkOut}T00:00:00Z`)
  const day = 24 * 60 * 60 * 1000
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || (end - start) / day > 30) return []
  const dates: string[] = []
  for (let time = start; time < end; time += day) dates.push(new Date(time).toISOString().slice(0, 10))
  return dates
}

function safeMinorUnits(value: string) {
  try { return decimalToMinorUnits(value) } catch { return null }
}

function previewAgentReply(language: string, status: 'need-destination' | 'no-recommendation' | 'recommendation' | 'results' | 'no-results', request: TripRequest, recommendedCity = '', resultCount = 0) {
  const city = status === 'recommendation' ? recommendedCity : request.destination
  const copy: Record<string, Record<typeof status, (city: string, count: number) => string>> = {
    'en-IN': {
      'need-destination': () => 'Which destination city should I look in? You can also change dates, travellers and budget in the trip form.',
      'no-recommendation': () => 'I could not find a matching stay in the shared sample data for your budget and dates. Try a higher budget or different dates.',
      recommendation: (name) => `Based on your dates and budget, ${name} has a matching stay in the shared sample data. Prices are static preview values, not live availability. What do you enjoy: culture, nature, food or a slower pace?`,
      results: (name, count) => `I found ${count} stay option${count === 1 ? '' : 's'} in ${name} for ${request.startDate} to ${request.endDate}. These are static sample results, not live availability.`,
      'no-results': (name) => `I could not find a stay in ${name} for those dates and filters in the sample data. Try different dates or a higher budget.`,
    },
    hi: {
      'need-destination': () => 'आप किस शहर में जाना चाहते हैं? यात्रा फॉर्म में तारीखें, यात्री और बजट भी बदल सकते हैं।',
      'no-recommendation': () => 'आपके बजट और तारीखों में साझा नमूना डेटा में कोई ठहराव नहीं मिला। बजट बढ़ाएँ या दूसरी तारीखें आज़माएँ।',
      recommendation: (name) => `आपकी तारीखों और बजट के आधार पर साझा नमूना डेटा में ${name} एक अच्छा विकल्प दिखता है। कीमतें स्थिर नमूना हैं, लाइव उपलब्धता नहीं। आपको संस्कृति, प्रकृति, खानपान या आरामदायक यात्रा में क्या पसंद है?`,
      results: (name, count) => `${name} में ${request.startDate} से ${request.endDate} तक ${count} ठहरने के विकल्प मिले। ये स्थिर नमूना डेटा के परिणाम हैं, लाइव उपलब्धता नहीं।`,
      'no-results': (name) => `इन तारीखों और फ़िल्टर के साथ ${name} के लिए नमूना डेटा में ठहराव नहीं मिला। दूसरी तारीखें या अधिक बजट आज़माएँ।`,
    },
    ta: {
      'need-destination': () => 'எந்த நகரத்தைத் தேட வேண்டும்? பயணப் படிவத்தில் தேதிகள், பயணிகள், பட்ஜெட்டையும் மாற்றலாம்.',
      'no-recommendation': () => 'உங்கள் பட்ஜெட் மற்றும் தேதிகளில் பொருத்தமான தங்குமிடம் இல்லை. அதிக பட்ஜெட் அல்லது வேறு தேதிகளை முயற்சிக்கவும்.',
      recommendation: (name) => `உங்கள் தேதிகளுக்கும் பட்ஜெட்டுக்கும் ${name}-இல் மாதிரித் தரவில் தங்குமிடம் உள்ளது. இவை நிலையான முன்னோட்ட விலைகள்; நேரடி கிடைப்பல்ல. கலாசாரம், இயற்கை, உணவு அல்லது நிதானமான பயணம் — எது பிடிக்கும்?`,
      results: (name, count) => `${request.startDate} முதல் ${request.endDate} வரை ${name}-இல் ${count} தங்குமிடத் தேர்வுகள் கிடைத்தன. இவை மாதிரி முடிவுகள்; நேரடி கிடைப்பல்ல.`,
      'no-results': (name) => `இந்தத் தேதிகளிலும் வடிகட்டிகளிலும் ${name}-இல் தங்குமிடம் இல்லை. வேறு தேதிகள் அல்லது அதிக பட்ஜெட்டை முயற்சிக்கவும்.`,
    },
    te: {
      'need-destination': () => 'ఏ నగరాన్ని వెతకాలి? ట్రిప్ ఫారమ్‌లో తేదీలు, ప్రయాణికులు, బడ్జెట్‌ను కూడా మార్చవచ్చు.',
      'no-recommendation': () => 'మీ బడ్జెట్, తేదీలకు సరిపడే బస నమూనా డేటాలో లేదు. ఎక్కువ బడ్జెట్ లేదా వేరే తేదీలను ప్రయత్నించండి.',
      recommendation: (name) => `మీ తేదీలు, బడ్జెట్‌కు ${name}లో నమూనా డేటా ప్రకారం బస ఉంది. ధరలు నమూనా అంచనాలు మాత్రమే; ప్రత్యక్ష లభ్యత కాదు. సంస్కృతి, ప్రకృతి, ఆహారం లేదా నెమ్మదైన ప్రయాణం — మీకు ఏది ఇష్టం?`,
      results: (name, count) => `${request.startDate} నుంచి ${request.endDate} వరకు ${name}లో ${count} బస ఎంపికలు దొరికాయి. ఇవి నమూనా ఫలితాలు మాత్రమే; ప్రత్యక్ష లభ్యత కాదు.`,
      'no-results': (name) => 'ఈ తేదీలు, ఫిల్టర్‌లకు ' + name + 'లో నమూనా డేటా ప్రకారం బస దొరకలేదు. వేరే తేదీలు లేదా ఎక్కువ బడ్జెట్ ప్రయత్నించండి.',
    },
    bn: {
      'need-destination': () => 'কোন শহরে খুঁজব? ভ্রমণ ফর্মে তারিখ, ভ্রমণকারীর সংখ্যা ও বাজেটও বদলাতে পারেন।',
      'no-recommendation': () => 'আপনার বাজেট ও তারিখে শেয়ার করা নমুনা ডেটায় থাকার জায়গা মেলেনি। বাজেট বাড়িয়ে বা অন্য তারিখ দিয়ে দেখুন।',
      recommendation: (name) => `আপনার তারিখ ও বাজেট অনুযায়ী ${name}-এ নমুনা ডেটায় থাকার বিকল্প আছে। দাম স্থির নমুনা, সরাসরি উপলভ্যতা নয়। সংস্কৃতি, প্রকৃতি, খাবার নাকি ধীরেসুস্থে ঘোরা—কোনটি পছন্দ?`,
      results: (name, count) => `${request.startDate} থেকে ${request.endDate} তারিখে ${name}-এ ${count}টি থাকার বিকল্প মিলেছে। এগুলি নমুনা ফল, সরাসরি উপলভ্যতা নয়।`,
      'no-results': (name) => `এই তারিখ ও শর্তে ${name}-এ নমুনা ডেটায় থাকার জায়গা মেলেনি। অন্য তারিখ বা বেশি বাজেট দিয়ে দেখুন।`,
    },
    mr: {
      'need-destination': () => 'कोणते शहर शोधायचे? सहलीच्या फॉर्ममध्ये तारखा, प्रवासी आणि अंदाजपत्रक बदलू शकता.',
      'no-recommendation': () => 'तुमच्या अंदाजपत्रकात आणि तारखांमध्ये सामायिक नमुना डेटात निवास मिळाला नाही. जास्त अंदाजपत्रक किंवा वेगळ्या तारखा वापरून पाहा.',
      recommendation: (name) => `तुमच्या तारखा आणि अंदाजपत्रकानुसार सामायिक नमुना डेटात ${name} येथे निवासाचा पर्याय आहे. किंमती नमुना आहेत, थेट उपलब्धता नाही. संस्कृती, निसर्ग, खाद्यपदार्थ की निवांत प्रवास — तुम्हाला काय आवडेल?`,
      results: (name, count) => `${request.startDate} ते ${request.endDate} दरम्यान ${name} येथे ${count} निवास पर्याय मिळाले. हे नमुना निकाल आहेत; थेट उपलब्धता नाही.`,
      'no-results': (name) => `या तारखा आणि अटींसाठी ${name} येथे नमुना डेटात निवास मिळाला नाही. वेगळ्या तारखा किंवा जास्त अंदाजपत्रक वापरून पाहा.`,
    },
    kn: {
      'need-destination': () => 'ಯಾವ ನಗರಕ್ಕಾಗಿ ಹುಡುಕಲಿ? ಪ್ರವಾಸದ ಫಾರ್ಮ್‌ನಲ್ಲಿ ದಿನಾಂಕ, ಪ್ರಯಾಣಿಕರ ಸಂಖ್ಯೆ ಮತ್ತು ಬಜೆಟ್ ಬದಲಾಯಿಸಬಹುದು.',
      'no-recommendation': () => 'ನಿಮ್ಮ ದಿನಾಂಕ ಮತ್ತು ಬಜೆಟ್‌ಗೆ ತಕ್ಕ ವಾಸದ ಆಯ್ಕೆ ಮಾದರಿ ಮಾಹಿತಿಯಲ್ಲಿ ಸಿಗಲಿಲ್ಲ. ಬೇರೆ ದಿನಾಂಕ ಅಥವಾ ಹೆಚ್ಚಿನ ಬಜೆಟ್ ಪ್ರಯತ್ನಿಸಿ.',
      recommendation: (name) => `ನಿಮ್ಮ ದಿನಾಂಕ ಮತ್ತು ಬಜೆಟ್‌ಗೆ ${name}ನಲ್ಲಿ ವಾಸದ ಆಯ್ಕೆ ಇದೆ. ಇವು ಮಾದರಿ ದರಗಳು; ನೈಜ ಲಭ್ಯತೆ ಅಲ್ಲ. ನಿಮಗೆ ಸಂಸ್ಕೃತಿ, ಪ್ರಕೃತಿ, ಆಹಾರ ಅಥವಾ ಆರಾಮದಾಯಕ ಪ್ರವಾಸದಲ್ಲಿ ಯಾವುದು ಇಷ್ಟ?`,
      results: (name, count) => `${request.startDate}ರಿಂದ ${request.endDate}ರವರೆಗೆ ${name}ನಲ್ಲಿ ${count} ವಾಸದ ಆಯ್ಕೆಗಳು ಸಿಕ್ಕಿವೆ. ಇವು ಮಾದರಿ ಫಲಿತಾಂಶಗಳು; ನೈಜ ಲಭ್ಯತೆ ಅಲ್ಲ.`,
      'no-results': (name) => `ಆ ದಿನಾಂಕ ಮತ್ತು ಆಯ್ಕೆಗಳಿಗೆ ${name}ನಲ್ಲಿ ವಾಸ ಸಿಗಲಿಲ್ಲ. ಬೇರೆ ದಿನಾಂಕ ಅಥವಾ ಹೆಚ್ಚಿನ ಬಜೆಟ್ ಪ್ರಯತ್ನಿಸಿ.`,
    },
  }
  return (copy[language] ?? copy['en-IN'])[status](city, resultCount)
}

function previewAgentSteps(language: string, request: TripRequest, recommendation: boolean, matched: boolean) {
  const steps: Record<string, (trip: TripRequest, recommend: boolean, hasMatch: boolean) => string[]> = {
    'en-IN': (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['Compared destinations with matching dated stays and budget'] : []), `Matched destination: ${trip.destination}`, `Checked dated room inventory (${trip.startDate} → ${trip.endDate})`, 'Applied traveller, currency and budget filters']
      : recommend ? ['Compared destinations in the shared dated inventory', 'No match for the current filters'] : ['Read your request', 'Waiting for a destination city'],
    hi: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['तारीख़ वाली उपलब्धता और बजट से शहरों की तुलना की'] : []), `मंज़िल मिली: ${trip.destination}`, `कमरे की उपलब्धता देखी (${trip.startDate} → ${trip.endDate})`, 'यात्रियों, मुद्रा और बजट के फ़िल्टर लगाए']
      : recommend ? ['साझा डेटा में तारीख़ वाली उपलब्धता देखी', 'मौजूदा फ़िल्टर में विकल्प नहीं मिला'] : ['आपका अनुरोध पढ़ा', 'शहर की जानकारी चाहिए'],
    ta: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['தேதி இருப்பு மற்றும் பட்ஜெட்டின் அடிப்படையில் நகரங்களை ஒப்பிட்டது'] : []), `செல்லுமிடம்: ${trip.destination}`, `அறை இருப்பைச் சரிபார்த்தது (${trip.startDate} → ${trip.endDate})`, 'பயணிகள், நாணயம், பட்ஜெட் வடிகட்டிகளைப் பயன்படுத்தியது']
      : recommend ? ['பகிரப்பட்ட தேதியிட்ட இருப்பை ஒப்பிட்டது', 'தற்போதைய வடிகட்டிகளுக்கு பொருத்தம் இல்லை'] : ['உங்கள் கோரிக்கையைப் படித்தது', 'செல்லுமிட நகரம் தேவை'],
    te: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['తేదీల లభ్యత, బడ్జెట్‌తో నగరాలను పోల్చింది'] : []), `గమ్యస్థానం: ${trip.destination}`, `గది లభ్యత చూసింది (${trip.startDate} → ${trip.endDate})`, 'ప్రయాణికులు, కరెన్సీ, బడ్జెట్ ఫిల్టర్‌లను వర్తింపజేసింది']
      : recommend ? ['పంచుకున్న తేదీల ఇన్వెంటరీని పోల్చింది', 'ప్రస్తుత ఫిల్టర్‌లకు సరిపోలిక లేదు'] : ['మీ అభ్యర్థనను చదివింది', 'గమ్యస్థాన నగరం కావాలి'],
    bn: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['তারিখের উপলভ্যতা ও বাজেট দেখে শহর তুলনা করেছে'] : []), `গন্তব্য মিলেছে: ${trip.destination}`, `ঘরের উপলভ্যতা দেখা হয়েছে (${trip.startDate} → ${trip.endDate})`, 'ভ্রমণকারী, মুদ্রা ও বাজেটের শর্ত মিলিয়েছে']
      : recommend ? ['শেয়ার করা তারিখের ইনভেন্টরি তুলনা করেছে', 'বর্তমান শর্তে কিছু মেলেনি'] : ['আপনার অনুরোধ পড়েছে', 'গন্তব্য শহর জানা দরকার'],
    mr: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['दिनांकित उपलब्धता आणि अंदाजपत्रकानुसार शहरांची तुलना केली'] : []), `ठिकाण जुळले: ${trip.destination}`, `खोलीची उपलब्धता तपासली (${trip.startDate} → ${trip.endDate})`, 'प्रवासी, चलन आणि अंदाजपत्रकाचे निकष लावले']
      : recommend ? ['सामायिक दिनांकित उपलब्धतेची तुलना केली', 'सध्याच्या निकषांमध्ये पर्याय नाही'] : ['तुमची विनंती वाचली', 'ठिकाणाचे शहर आवश्यक आहे'],
    kn: (trip, recommend, hasMatch) => hasMatch
      ? [...(recommend ? ['ದಿನಾಂಕ ಮತ್ತು ಬಜೆಟ್‌ಗೆ ಹೊಂದುವ ತಾಣಗಳನ್ನು ಹೋಲಿಸಲಾಗಿದೆ'] : []), `ಆಯ್ಕೆಯಾದ ತಾಣ: ${trip.destination}`, `ಕೊಠಡಿ ಲಭ್ಯತೆ ಪರಿಶೀಲಿಸಲಾಗಿದೆ (${trip.startDate} → ${trip.endDate})`, 'ಪ್ರಯಾಣಿಕರ ಸಂಖ್ಯೆ, ಕರೆನ್ಸಿ ಮತ್ತು ಬಜೆಟ್ ಅನ್ವಯಿಸಲಾಗಿದೆ']
      : recommend ? ['ಹಂಚಿದ ಮಾದರಿ ಮಾಹಿತಿಯಲ್ಲಿನ ತಾಣಗಳನ್ನು ಹೋಲಿಸಲಾಗಿದೆ', 'ಈ ಆಯ್ಕೆಗಳಿಗೆ ಹೊಂದುವ ಫಲಿತಾಂಶ ಸಿಗಲಿಲ್ಲ'] : ['ನಿಮ್ಮ ವಿನಂತಿಯನ್ನು ಓದಲಾಗಿದೆ', 'ದಯವಿಟ್ಟು ತಾಣದ ನಗರವನ್ನು ತಿಳಿಸಿ'],
  }
  return (steps[language] ?? steps['en-IN'])(request, recommendation, matched)
}

function normalize(value: string) {
  return value.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim()
}

function escapeRegExp(value: string) { return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') }
function pause(ms: number) { return new Promise((resolve) => setTimeout(resolve, ms)) }
