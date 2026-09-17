import { motion, type Variants } from 'framer-motion'
import { ArrowRight, Play, Sparkles, Zap, Globe } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

const fadeInUp: Variants = {
  hidden: { opacity: 0, y: 40 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.8,
      ease: [0.22, 1, 0.36, 1] as [number, number, number, number],
    },
  },
}

export default function HeroSection() {
  const navigate = useNavigate()

  return (
    <section className="relative flex min-h-[90vh] flex-col items-center justify-center overflow-hidden px-4 py-20 text-center">
      {/* Ambient glow orbs */}
      <motion.div
        animate={{
          scale: [1, 1.1, 1],
          opacity: [0.4, 0.6, 0.4],
        }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: 'easeInOut',
        }}
        className="pointer-events-none absolute -left-32 top-20 h-96 w-96 rounded-full bg-accent/5 blur-[100px]"
      />
      <motion.div
        animate={{
          scale: [1, 1.1, 1],
          opacity: [0.4, 0.6, 0.4],
        }}
        transition={{
          duration: 4,
          repeat: Infinity,
          ease: 'easeInOut',
          delay: 2,
        }}
        className="pointer-events-none absolute -right-32 bottom-20 h-96 w-96 rounded-full bg-accent2/5 blur-[100px]"
      />

      {/* Label */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={fadeInUp}
        transition={{ delay: 0 }}
        className="mb-8 flex items-center gap-2"
      >
        <Sparkles className="h-4 w-4 text-accent" />
        <span className="text-xs font-medium uppercase tracking-[0.3em] text-accent">
          Where Transparency Becomes Reality
        </span>
      </motion.div>

      {/* Main Headline */}
      <motion.h1
        initial="hidden"
        animate="visible"
        variants={fadeInUp}
        transition={{ delay: 0.1 }}
        className="max-w-4xl font-serif text-5xl leading-[1.1] tracking-tight text-text sm:text-6xl md:text-7xl lg:text-8xl"
      >
        <span className="block">Track</span>
        <span className="block bg-linear-to-r from-accent via-accent2 to-accent3 bg-clip-text text-transparent">
          Beyond
        </span>
        <span className="block text-3xl uppercase tracking-[0.2em] text-muted sm:text-4xl md:text-5xl">
          The Ordinary
        </span>
      </motion.h1>

      {/* Subtitle */}
      <motion.p
        initial="hidden"
        animate="visible"
        variants={fadeInUp}
        transition={{ delay: 0.2 }}
        className="mx-auto mt-8 max-w-xl text-base leading-relaxed text-muted sm:text-lg"
      >
        Veritras is the next generation supply chain platform designed to bring 
        trust to life. Track, verify, and transcend the limits of transparency 
        with blockchain-powered provenance.
      </motion.p>

      {/* CTA Buttons */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={fadeInUp}
        transition={{ delay: 0.3 }}
        className="mt-10 flex flex-wrap items-center justify-center gap-4"
      >
        <button
          onClick={() => navigate('/products')}
          className="group relative flex items-center gap-2 rounded-full bg-linear-to-r from-accent/20 to-accent2/20 px-8 py-4 text-sm font-medium text-text backdrop-blur-sm transition-all hover:scale-105 hover:shadow-[0_0_30px_rgba(200,240,96,0.2)] border border-accent/20"
        >
          Explore Now
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
        </button>
        <button
          onClick={() => navigate('/verify')}
          className="group flex items-center gap-2 rounded-full border border-border bg-surface/50 px-8 py-4 text-sm font-medium text-text backdrop-blur-sm transition-all hover:bg-surface hover:border-muted/50"
        >
          <Play className="h-4 w-4" />
          Verify Product
        </button>
      </motion.div>

      {/* Feature highlights */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={fadeInUp}
        transition={{ delay: 0.5 }}
        className="mt-20 grid grid-cols-1 gap-6 sm:grid-cols-3"
      >
        {[
          {
            icon: Sparkles,
            title: 'On-Chain Provenance',
            desc: 'Every product registered on the Ethereum Sepolia testnet with immutable records.',
          },
          {
            icon: Zap,
            title: 'Real-Time Tracking',
            desc: 'Follow shipments through every checkpoint with live status updates.',
          },
          {
            icon: Globe,
            title: 'Global Verification',
            desc: 'Anyone, anywhere can verify product authenticity by ID in seconds.',
          },
        ].map((feature, i) => (
          <motion.div
            key={feature.title}
            initial="hidden"
            animate="visible"
            variants={fadeInUp}
            transition={{ delay: 0.6 + i * 0.1 }}
            className="group relative rounded-2xl border border-border/50 bg-surface/30 p-6 backdrop-blur-md transition-all hover:border-accent/20 hover:bg-surface/50"
          >
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl bg-accent/10">
              <feature.icon className="h-5 w-5 text-accent" />
            </div>
            <h3 className="mb-2 text-sm font-semibold text-text">{feature.title}</h3>
            <p className="text-xs leading-relaxed text-muted">{feature.desc}</p>
            <div className="absolute inset-0 rounded-2xl bg-linear-to-br from-accent/5 to-transparent opacity-0 transition-opacity group-hover:opacity-100" />
          </motion.div>
        ))}
      </motion.div>
    </section>
  )
}
