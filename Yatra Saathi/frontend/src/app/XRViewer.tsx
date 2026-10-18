import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { HDRLoader } from 'three/examples/jsm/loaders/HDRLoader.js'
import { Compass, Glasses, Minus, Plus, Smartphone, X } from 'lucide-react'
import { useLanguage } from '../i18n/LanguageContext'

// "Explore in XR": an interactive 360° scene you can drag around (or steer with your phone),
// and enter in VR on a WebXR headset browser. The dataset has no 360° media, so each
// destination gets a CC0 panorama from Poly Haven matching its kind of place -- labelled as
// illustrative, never as a view of the destination itself.

type SceneType = 'city' | 'coast' | 'mountain' | 'desert' | 'heritage' | 'lake'
const SCENES: Record<SceneType, { id: string; name: string; author: string }> = {
  city: { id: 'shanghai_bund', name: 'Shanghai Bund', author: 'Greg Zaal' },
  coast: { id: 'spiaggia_di_mondello', name: 'Spiaggia di Mondello', author: 'Andreas Mischok' },
  mountain: { id: 'immenstadter_horn', name: 'Immenstädter Horn', author: 'Andreas Mischok' },
  desert: { id: 'goegap', name: 'Goegap', author: 'Greg Zaal' },
  heritage: { id: 'amphitheatre_zanzibar_fort', name: 'Amphitheatre Zanzibar Fort', author: 'Dimitrios Savva' },
  lake: { id: 'lakeside', name: 'Lakeside', author: 'Greg Zaal' },
}
const CITY_SCENE: Record<string, SceneType> = Object.fromEntries(Object.entries({
  coast: ['Panaji', 'Gokarna', 'Kochi', 'Pondicherry', 'Puri', 'Visakhapatnam', 'Male', 'Bali', 'Colombo', 'Mumbai', 'Chennai', 'Thiruvananthapuram'],
  mountain: ['Shimla', 'Manali', 'Rishikesh', 'Leh', 'Darjeeling', 'Gangtok', 'Shillong', 'Ooty', 'Munnar', 'Wayanad', 'Kandy', 'Pokhara', 'Kathmandu', 'Thimphu', 'Zurich'],
  desert: ['Jaisalmer', 'Bhuj'],
  heritage: ['Jaipur', 'Jodhpur', 'Agra', 'Varanasi', 'Lucknow', 'Amritsar', 'Aurangabad', 'Hampi', 'Madurai', 'Thanjavur', 'Mysuru', 'Tirupati', 'Bhubaneswar', 'Kyoto'],
  lake: ['Udaipur', 'Srinagar', 'Nainital', 'Alleppey', 'Guwahati'],
}).flatMap(([type, cities]) => cities.map((city) => [city.toLowerCase(), type as SceneType])))
const sceneFor = (city: string): SceneType => CITY_SCENE[city.trim().toLowerCase()] ?? 'city'
const hdrUrl = (id: string, res: '1k' | '2k') => `https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/${res}/${id}_${res}.hdr`

type XRNavigator = Navigator & { xr?: { isSessionSupported: (mode: string) => Promise<boolean>; requestSession: (mode: string, init?: object) => Promise<XRSession> } }
type OrientationEventCtor = typeof DeviceOrientationEvent & { requestPermission?: () => Promise<'granted' | 'denied'> }

export default function XRViewer({ city, photoUrl, onClose }: { city: string; photoUrl: string; onClose: () => void }) {
  const { t } = useLanguage()
  const mount = useRef<HTMLDivElement>(null)
  const view = useRef({ lon: 0, lat: 0, fov: 75, interacted: false, motion: false })
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const [scene, setScene] = useState<SceneType>(() => sceneFor(city))
  const [state, setState] = useState<'loading' | 'ready' | 'sharp' | 'error'>('loading')
  const [vrSupported, setVrSupported] = useState(false)
  const [motionOn, setMotionOn] = useState(false)
  const [fov, setFov] = useState(75)

  // WebGL scene: an inside-out sphere wearing the panorama.
  useEffect(() => {
    const host = mount.current
    if (!host) return
    let renderer: THREE.WebGLRenderer
    try { renderer = new THREE.WebGLRenderer({ antialias: true }) } catch { setState('error'); return }
    rendererRef.current = renderer
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.toneMapping = THREE.ACESFilmicToneMapping
    renderer.toneMappingExposure = 1.1
    renderer.xr.enabled = true
    host.appendChild(renderer.domElement)
    const camera = new THREE.PerspectiveCamera(75, 1, 0.1, 1000)
    const world = new THREE.Scene()
    const geometry = new THREE.SphereGeometry(50, 64, 32)
    geometry.scale(-1, 1, 1)
    const material = new THREE.MeshBasicMaterial({ color: 0x223a30 })
    world.add(new THREE.Mesh(geometry, material))

    const resize = () => {
      const { clientWidth: w, clientHeight: h } = host
      renderer.setSize(w, h); camera.aspect = w / Math.max(h, 1); camera.updateProjectionMatrix()
    }
    resize()
    const observer = new ResizeObserver(resize); observer.observe(host)

    const target = new THREE.Vector3()
    renderer.setAnimationLoop(() => {
      const v = view.current
      if (!v.interacted && !v.motion && !renderer.xr.isPresenting) v.lon += 0.03
      v.lat = Math.max(-85, Math.min(85, v.lat))
      const phi = THREE.MathUtils.degToRad(90 - v.lat), theta = THREE.MathUtils.degToRad(v.lon)
      target.set(500 * Math.sin(phi) * Math.cos(theta), 500 * Math.cos(phi), 500 * Math.sin(phi) * Math.sin(theta))
      if (camera.fov !== v.fov) { camera.fov = v.fov; camera.updateProjectionMatrix() }
      camera.lookAt(target)
      renderer.render(world, camera)
    })

    // Load the 1k panorama fast, then swap in the sharper 2k one.
    let alive = true
    const textures: THREE.Texture[] = []
    const loader = new HDRLoader()
    const apply = (texture: THREE.DataTexture) => {
      if (!alive) { texture.dispose(); return }
      textures.push(texture)
      material.map = texture; material.color.set(0xffffff); material.needsUpdate = true
    }
    const { id } = SCENES[scene]
    setState('loading')
    loader.loadAsync(hdrUrl(id, '1k'))
      .then((tex) => { apply(tex); if (alive) setState('ready'); return loader.loadAsync(hdrUrl(id, '2k')) })
      .then((tex) => { apply(tex); if (alive) setState('sharp') })
      .catch(() => { if (alive) setState((s) => (s === 'loading' ? 'error' : s)) })

    // Drag / touch to look around, wheel or pinch to zoom.
    let drag: { x: number; y: number; lon: number; lat: number } | null = null
    const pinch = new Map<number, { x: number; y: number }>()
    let pinchStart = 0, fovStart = 75
    const el = renderer.domElement
    const down = (e: PointerEvent) => {
      view.current.interacted = true
      pinch.set(e.pointerId, { x: e.clientX, y: e.clientY }); el.setPointerCapture(e.pointerId)
      if (pinch.size === 2) { const [a, b] = [...pinch.values()]; pinchStart = Math.hypot(a.x - b.x, a.y - b.y); fovStart = view.current.fov; drag = null }
      else drag = { x: e.clientX, y: e.clientY, lon: view.current.lon, lat: view.current.lat }
    }
    const move = (e: PointerEvent) => {
      if (pinch.has(e.pointerId)) pinch.set(e.pointerId, { x: e.clientX, y: e.clientY })
      if (pinch.size === 2 && pinchStart) {
        const [a, b] = [...pinch.values()]
        setZoom(fovStart * pinchStart / Math.max(Math.hypot(a.x - b.x, a.y - b.y), 1))
      } else if (drag) {
        const speed = view.current.fov / el.clientHeight
        view.current.lon = drag.lon - (e.clientX - drag.x) * speed
        view.current.lat = drag.lat + (e.clientY - drag.y) * speed
      }
    }
    const up = (e: PointerEvent) => { pinch.delete(e.pointerId); if (pinch.size < 2) pinchStart = 0; drag = null }
    const wheel = (e: WheelEvent) => { e.preventDefault(); view.current.interacted = true; setZoom(view.current.fov + e.deltaY * 0.05) }
    el.addEventListener('pointerdown', down); el.addEventListener('pointermove', move)
    el.addEventListener('pointerup', up); el.addEventListener('pointercancel', up)
    el.addEventListener('wheel', wheel, { passive: false })

    return () => {
      alive = false
      renderer.setAnimationLoop(null)
      void renderer.xr.getSession()?.end().catch(() => undefined)
      observer.disconnect()
      el.removeEventListener('pointerdown', down); el.removeEventListener('pointermove', move)
      el.removeEventListener('pointerup', up); el.removeEventListener('pointercancel', up); el.removeEventListener('wheel', wheel)
      textures.forEach((tex) => tex.dispose()); geometry.dispose(); material.dispose(); renderer.dispose()
      el.remove(); rendererRef.current = null
    }
  }, [scene])

  function setZoom(next: number) {
    view.current.fov = Math.max(35, Math.min(95, next)); setFov(Math.round(view.current.fov))
  }

  // Keyboard: arrows look around, +/- zoom, Esc closes.
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      const v = view.current
      if (e.key === 'Escape') onClose()
      else if (e.key === 'ArrowLeft') { v.interacted = true; v.lon -= 5 } else if (e.key === 'ArrowRight') { v.interacted = true; v.lon += 5 }
      else if (e.key === 'ArrowUp') { v.interacted = true; v.lat += 5 } else if (e.key === 'ArrowDown') { v.interacted = true; v.lat -= 5 }
      else if (e.key === '+' || e.key === '=') setZoom(v.fov - 5)
      else if (e.key === '-') setZoom(v.fov + 5)
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [onClose])

  // WebXR headsets (Quest browser, etc.).
  useEffect(() => {
    void (navigator as XRNavigator).xr?.isSessionSupported('immersive-vr').then(setVrSupported).catch(() => setVrSupported(false))
  }, [])
  async function enterVR() {
    const renderer = rendererRef.current
    const xr = (navigator as XRNavigator).xr
    if (!renderer || !xr) return
    const session = await xr.requestSession('immersive-vr', { optionalFeatures: ['local-floor'] })
    await renderer.xr.setSession(session)
  }

  // Phone motion: look around by moving the phone.
  useEffect(() => {
    if (!motionOn) { view.current.motion = false; return }
    view.current.motion = true; view.current.interacted = true
    const orient = (e: DeviceOrientationEvent) => {
      if (e.alpha == null || e.beta == null) return
      view.current.lon = -e.alpha; view.current.lat = e.beta - 90
    }
    window.addEventListener('deviceorientation', orient)
    return () => window.removeEventListener('deviceorientation', orient)
  }, [motionOn])
  async function toggleMotion() {
    const ctor = window.DeviceOrientationEvent as OrientationEventCtor | undefined
    if (!motionOn && ctor?.requestPermission && (await ctor.requestPermission().catch(() => 'denied')) !== 'granted') return
    setMotionOn(!motionOn)
  }
  const hasMotion = typeof window !== 'undefined' && 'DeviceOrientationEvent' in window && window.matchMedia('(pointer: coarse)').matches

  const info = SCENES[scene]
  const types: SceneType[] = ['city', 'coast', 'mountain', 'desert', 'heritage', 'lake']
  return <div className="modal-backdrop xr-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
    <section className="xr-preview-modal xr-viewer" role="dialog" aria-modal="true" aria-labelledby="xr-preview-title">
      <button className="modal-close" aria-label={t('xr.close')} onClick={onClose}><X size={19} /></button>
      <div className="xr-stage">
        {state === 'error'
          ? <div className="xr-fallback" style={{ backgroundImage: `linear-gradient(0deg,#10231dcc,transparent 62%),url("${photoUrl}")` }}><p>{t('xr.unavailable')}</p></div>
          : <div className="xr-canvas" ref={mount} aria-label={t('xr.dragHint')} />}
        <div className="xr-overlay">
          <span className="xr-preview-badge"><Compass size={14} /> {t('xr.badge')}</span>
          <div><span>{t('xr.label')}</span><h2 id="xr-preview-title">{city}</h2></div>
        </div>
        {state === 'loading' && <div className="xr-loading"><span className="spinner" /> {t('xr.loading')}</div>}
        {state !== 'error' && <div className="xr-hint">{t('xr.dragHint')}</div>}
      </div>
      <div className="xr-preview-controls">
        <div className="xr-scene-picker" role="group" aria-label={t('xr.sceneLabel')}>
          {types.map((type) => <button key={type} className={type === scene ? 'selected' : ''} onClick={() => { view.current.interacted = false; setScene(type) }}>{t(`xr.scene.${type}`)}</button>)}
        </div>
        <div className="xr-actions">
          {vrSupported && <button className="xr-vr-button" onClick={() => void enterVR()}><Glasses size={15} /> {t('xr.enterVR')}</button>}
          {hasMotion && <button className={motionOn ? 'selected' : ''} onClick={() => void toggleMotion()}><Smartphone size={15} /> {t('xr.motion')}</button>}
          <div className="xr-zoom-controls"><button onClick={() => setZoom(fov + 8)} aria-label={t('xr.zoomOut')}><Minus size={14} /></button><span>{Math.round(75 / fov * 100)}%</span><button onClick={() => setZoom(fov - 8)} aria-label={t('xr.zoomIn')}><Plus size={14} /></button></div>
        </div>
        <p className="xr-credit">{t('xr.illustrative').replace('{scene}', info.name).replace('{author}', info.author).replace('{city}', city)}</p>
      </div>
    </section>
  </div>
}
