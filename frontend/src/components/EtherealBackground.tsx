import { useEffect, useRef } from 'react'

interface Particle {
  x: number
  y: number
  size: number
  speedX: number
  speedY: number
  opacity: number
  color: string
}

export default function EtherealBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const isMountedRef = useRef(true)

  useEffect(() => {
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return
    const canvas = canvasRef.current
    if (!canvas) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let animationFrameId = 0
    let particles: Particle[] = []
    let time = 0

    const colors = ['#c8f060', '#60d0f0', '#f0a060', '#d060f0']

    const resize = () => {
      canvas.width = window.innerWidth
      canvas.height = window.innerHeight
      initParticles()
    }

    const defer = (cb: () => void): number => {
      if (window.requestIdleCallback) {
        return window.requestIdleCallback(cb, { timeout: 2000 })
      }
      return window.setTimeout(cb, 1500)
    }

    const initParticles = () => {
      particles = []
      const count = Math.floor((canvas.width * canvas.height) / 12000)
      for (let i = 0; i < count; i++) {
        particles.push({
          x: Math.random() * canvas.width,
          y: Math.random() * canvas.height,
          size: Math.random() * 2 + 0.5,
          speedX: (Math.random() - 0.5) * 0.3,
          speedY: (Math.random() - 0.5) * 0.3,
          opacity: Math.random() * 0.4 + 0.1,
          color: colors[Math.floor(Math.random() * colors.length)],
        })
      }
    }

    const draw = () => {
      time += 0.005
      ctx.fillStyle = '#0a0a0a'
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // Draw soft gradient orbs
      const orb1 = ctx.createRadialGradient(
        canvas.width * 0.3,
        canvas.height * 0.4 + Math.sin(time) * 50,
        0,
        canvas.width * 0.3,
        canvas.height * 0.4,
        canvas.width * 0.5
      )
      orb1.addColorStop(0, 'rgba(96, 208, 240, 0.04)')
      orb1.addColorStop(1, 'rgba(96, 208, 240, 0)')
      ctx.fillStyle = orb1
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      const orb2 = ctx.createRadialGradient(
        canvas.width * 0.7,
        canvas.height * 0.6 + Math.cos(time * 0.8) * 40,
        0,
        canvas.width * 0.7,
        canvas.height * 0.6,
        canvas.width * 0.4
      )
      orb2.addColorStop(0, 'rgba(200, 240, 96, 0.03)')
      orb2.addColorStop(1, 'rgba(200, 240, 96, 0)')
      ctx.fillStyle = orb2
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      const orb3 = ctx.createRadialGradient(
        canvas.width * 0.5,
        canvas.height * 0.3 + Math.sin(time * 1.2) * 30,
        0,
        canvas.width * 0.5,
        canvas.height * 0.3,
        canvas.width * 0.6
      )
      orb3.addColorStop(0, 'rgba(208, 96, 240, 0.02)')
      orb3.addColorStop(1, 'rgba(208, 96, 240, 0)')
      ctx.fillStyle = orb3
      ctx.fillRect(0, 0, canvas.width, canvas.height)

      // Draw particles
      particles.forEach((p) => {
        p.x += p.speedX
        p.y += p.speedY

        if (p.x < 0) p.x = canvas.width
        if (p.x > canvas.width) p.x = 0
        if (p.y < 0) p.y = canvas.height
        if (p.y > canvas.height) p.y = 0

        const flicker = Math.sin(time * 3 + p.x * 0.01) * 0.3 + 0.7

        ctx.beginPath()
        ctx.arc(p.x, p.y, p.size, 0, Math.PI * 2)
        ctx.fillStyle = p.color
        ctx.globalAlpha = p.opacity * flicker
        ctx.fill()


      })

      ctx.globalAlpha = 1

      // Draw subtle grid lines
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.015)'
      ctx.lineWidth = 1
      const gridSize = 80
      for (let x = 0; x < canvas.width; x += gridSize) {
        ctx.beginPath()
        ctx.moveTo(x, 0)
        ctx.lineTo(x, canvas.height)
        ctx.stroke()
      }
      for (let y = 0; y < canvas.height; y += gridSize) {
        ctx.beginPath()
        ctx.moveTo(0, y)
        ctx.lineTo(canvas.width, y)
        ctx.stroke()
      }

      animationFrameId = requestAnimationFrame(draw)
    }

    let idleHandle: number | undefined
    idleHandle = defer(() => {
      if (!isMountedRef.current) return
      resize()
      window.addEventListener('resize', resize)
      animationFrameId = requestAnimationFrame(draw)
    })

    return () => {
      isMountedRef.current = false
      if (window.cancelIdleCallback) {
        window.cancelIdleCallback(idleHandle!)
      } else {
        clearTimeout(idleHandle)
      }
      window.removeEventListener('resize', resize)
      cancelAnimationFrame(animationFrameId)
    }
  }, [])

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none fixed inset-0 z-0"
    />
  )
}
