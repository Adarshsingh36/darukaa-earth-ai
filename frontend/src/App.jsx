import { useState } from "react"
import {
  Activity,
  ArrowDown,
  ArrowUp,
  Bot,
  CheckCircle2,
  ChevronRight,
  CloudRain,
  Droplets,
  Leaf,
  MapPin,
  Send,
  Sprout,
  Thermometer,
  TreePine,
  Waves,
  Wind,
  XCircle
} from "lucide-react"

const API = "http://127.0.0.1:8080"

const initialEnvironment = {
  soil_organic_carbon: 0.3,
  soil_moisture: 12,
  rainfall_mm: 420,
  temperature_c: 31,
  land_use: "wheat monoculture",
  region: "semi-arid"
}

function MetricCard({ icon: Icon, label, value, unit, status }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.035] p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-400/10">
          <Icon size={18} className="text-emerald-300" />
        </div>

        {status && (
          <span className="rounded-full bg-amber-400/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
            {status}
          </span>
        )}
      </div>

      <div className="text-xs text-slate-500">{label}</div>

      <div className="mt-1 flex items-end gap-1">
        <span className="text-2xl font-semibold tracking-tight text-white">
          {value}
        </span>

        {unit && (
          <span className="mb-1 text-xs text-slate-500">
            {unit}
          </span>
        )}
      </div>
    </div>
  )
}

function EvidenceCard({ evidence }) {
  return (
    <div className="group rounded-xl border border-white/8 bg-white/[0.025] p-4 transition hover:border-emerald-400/20 hover:bg-white/[0.04]">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-400/10">
          <Leaf size={15} className="text-emerald-300" />
        </div>

        <div className="min-w-0">
          <div className="text-[10px] font-bold uppercase tracking-[0.16em] text-emerald-300">
            {evidence.source}
          </div>

          <div className="mt-1 text-sm font-medium text-slate-200">
            {evidence.title}
          </div>

          <div className="mt-1 text-xs text-slate-600">
            Knowledge record {evidence.id}
          </div>
        </div>

        <ChevronRight
          size={15}
          className="ml-auto mt-1 text-slate-700 transition group-hover:text-emerald-400"
        />
      </div>
    </div>
  )
}

function RecommendationCard({ recommendation, index }) {
  const Icon = index === 0 ? Sprout : TreePine

  return (
    <div className="rounded-2xl border border-emerald-400/10 bg-gradient-to-br from-emerald-400/[0.06] to-transparent p-5">
      <div className="flex items-start gap-4">
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-400/10">
          <Icon size={21} className="text-emerald-300" />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <h3 className="text-sm font-semibold leading-6 text-white">
              {recommendation.recommendation}
            </h3>

            <div className="rounded-full border border-emerald-400/15 bg-emerald-400/10 px-2.5 py-1 text-[11px] font-bold text-emerald-300">
              {Math.round(recommendation.confidence * 100)}% confidence
            </div>
          </div>

          <p className="mt-3 text-sm leading-6 text-slate-400">
            {recommendation.why_it_works}
          </p>

          <div className="mt-4 flex flex-wrap gap-2">
            {recommendation.impacted_metrics.map((metric) => (
              <span
                key={metric}
                className="rounded-lg border border-white/7 bg-black/15 px-2.5 py-1 text-[11px] text-slate-400"
              >
                {metric}
              </span>
            ))}
          </div>

          <div className="mt-4 flex items-center justify-between border-t border-white/6 pt-3">
            <span className="text-xs text-slate-500">
              Horizon:{" "}
              <span className="text-slate-300">
                {recommendation.time_horizon}
              </span>
            </span>

            <span className="flex items-center gap-1 text-xs text-emerald-300">
              Evidence-backed
              <CheckCircle2 size={13} />
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}

function App() {
  const [environment, setEnvironment] = useState(initialEnvironment)
  const [analysis, setAnalysis] = useState(null)
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const userMessage = input.trim()

    setMessages((prev) => [
      ...prev,
      {
        role: "user",
        content: userMessage
      }
    ])

    setInput("")
    setLoading(true)

    try {
      const response = await fetch(`${API}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          conversation_id: "darukaa-demo",
          message: userMessage
        })
      })

      if (!response.ok) {
        throw new Error("Backend request failed")
      }

      const data = await response.json()

      if (data.environment) {
        setEnvironment((prev) => ({
          ...prev,
          ...data.environment
        }))
      }

      if (data.type === "clarification") {
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.message
          }
        ])
      }

      if (data.type === "analysis") {
        setAnalysis(data.analysis)

        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.message
          }
        ])
      }
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "I couldn't connect to the Darukaa.Earth analysis engine. Please make sure the FastAPI backend is running on port 8080."
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  const reasoning = analysis?.reasoning_chain || [
    "Low soil organic carbon can reduce aggregate stability and water-retention capacity.",
    "Low rainfall increases seasonal water stress.",
    "Monoculture provides relatively low habitat and resource diversity.",
    "Together these constraints can amplify drought stress while limiting habitat niches."
  ]

  const recommendations = analysis?.recommendations || []

  const evidence = analysis?.retrieved_evidence || []

  return (
    <div className="min-h-screen bg-[#07110d] text-slate-200">
      {/* Header */}
      <header className="sticky top-0 z-30 border-b border-white/7 bg-[#07110d]/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1500px] items-center justify-between px-6 py-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-emerald-400/20 bg-emerald-400/10">
              <TreePine size={21} className="text-emerald-300" />
            </div>

            <div>
              <div className="text-sm font-bold tracking-[0.22em] text-white">
                DARUKAA<span className="text-emerald-300">.EARTH</span>
              </div>
              <div className="text-[10px] uppercase tracking-[0.16em] text-slate-600">
                Environmental Intelligence
              </div>
            </div>
          </div>

          <div className="hidden items-center gap-2 rounded-full border border-emerald-400/10 bg-emerald-400/5 px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300 sm:flex">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-300" />
            Intelligence Engine Online
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1500px] space-y-6 px-6 py-6">

        {/* Intro */}
        <section className="flex flex-col justify-between gap-4 lg:flex-row lg:items-end">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs text-slate-600">
              <MapPin size={13} />
              Environmental assessment workspace
            </div>

            <h1 className="text-3xl font-semibold tracking-tight text-white md:text-4xl">
              Ecosystem intelligence
              <span className="text-emerald-300"> in context.</span>
            </h1>

            <p className="mt-2 max-w-2xl text-sm leading-6 text-slate-500">
              Connect soil, climate, land-use and biodiversity signals to
              uncover ecological constraints and evidence-backed interventions.
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-xl border border-white/7 bg-white/[0.025] px-4 py-3">
            <Activity size={16} className="text-emerald-300" />
            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-600">
                Assessment mode
              </div>
              <div className="text-xs font-medium text-slate-300">
                Multi-metric reasoning
              </div>
            </div>
          </div>
        </section>

        {/* Top Grid */}
        <section className="grid gap-5 xl:grid-cols-[1.05fr_1.5fr_1fr]">

          {/* Site Profile */}
          <div className="rounded-2xl border border-white/7 bg-white/[0.025] p-5">
            <div className="mb-5 flex items-center justify-between">
              <div>
                <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                  Site profile
                </div>
                <div className="mt-1 text-sm font-medium text-white">
                  Current environmental state
                </div>
              </div>

              <div className="rounded-lg bg-white/[0.04] p-2">
                <Waves size={16} className="text-slate-500" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <MetricCard
                icon={Leaf}
                label="Soil organic carbon"
                value={environment.soil_organic_carbon ?? "—"}
                unit="%"
                status={environment.soil_organic_carbon !== undefined ? "Low" : null}
              />

              <MetricCard
                icon={Droplets}
                label="Soil moisture"
                value={environment.soil_moisture ?? "—"}
                unit="%"
              />

              <MetricCard
                icon={CloudRain}
                label="Annual rainfall"
                value={environment.rainfall_mm ?? "—"}
                unit="mm"
                status={environment.rainfall_mm ? "Dry" : null}
              />

              <MetricCard
                icon={Thermometer}
                label="Temperature"
                value={environment.temperature_c ?? "—"}
                unit="°C"
              />
            </div>

            <div className="mt-3 rounded-xl border border-white/7 bg-black/10 p-4">
              <div className="text-[10px] uppercase tracking-wider text-slate-600">
                Land use
              </div>

              <div className="mt-1 text-sm font-medium capitalize text-slate-200">
                {environment.land_use || "Not specified"}
              </div>

              <div className="mt-3 flex items-center gap-2">
                <Wind size={13} className="text-slate-600" />
                <span className="text-xs text-slate-500">
                  {environment.region || "Region not specified"}
                </span>
              </div>
            </div>
          </div>

          {/* Map */}
          <div className="relative min-h-[430px] overflow-hidden rounded-2xl border border-white/7 bg-[#0a1711]">
            <div className="absolute left-5 top-5 z-10">
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                Spatial context
              </div>
              <div className="mt-1 text-sm font-medium text-white">
                Environmental site
              </div>
            </div>

            {/* Map grid */}
            <div
              className="absolute inset-0 opacity-30"
              style={{
                backgroundImage:
                  "linear-gradient(rgba(112, 168, 128, 0.12) 1px, transparent 1px), linear-gradient(90deg, rgba(112, 168, 128, 0.12) 1px, transparent 1px)",
                backgroundSize: "55px 55px"
              }}
            />

            {/* Landscape shapes */}
            <div className="absolute -left-20 top-28 h-72 w-72 rounded-full border border-emerald-400/10 bg-emerald-400/[0.025]" />
            <div className="absolute right-[-80px] bottom-[-100px] h-96 w-96 rounded-full border border-emerald-400/10 bg-emerald-400/[0.025]" />

            {/* Site marker */}
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2">
              <div className="absolute -inset-8 animate-ping rounded-full bg-emerald-400/10" />
              <div className="relative flex h-14 w-14 items-center justify-center rounded-full border border-emerald-300/30 bg-emerald-400/15 shadow-[0_0_60px_rgba(52,211,153,0.12)]">
                <MapPin size={22} className="text-emerald-300" />
              </div>
            </div>

            <div className="absolute bottom-5 left-5 right-5 flex items-end justify-between">
              <div className="rounded-xl border border-white/7 bg-black/30 px-3 py-2 backdrop-blur-md">
                <div className="text-[9px] uppercase tracking-wider text-slate-600">
                  Location
                </div>
                <div className="mt-0.5 text-xs text-slate-400">
                  Coordinates not provided
                </div>
              </div>

              <div className="rounded-xl border border-white/7 bg-black/30 px-3 py-2 backdrop-blur-md">
                <div className="text-[9px] uppercase tracking-wider text-slate-600">
                  Data layers
                </div>
                <div className="mt-0.5 text-xs text-emerald-300">
                  6 environmental signals
                </div>
              </div>
            </div>
          </div>

          {/* Assessment */}
          <div className="rounded-2xl border border-white/7 bg-white/[0.025] p-5">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-400/10">
                <Bot size={17} className="text-emerald-300" />
              </div>

              <div>
                <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                  AI assessment
                </div>
                <div className="text-sm font-medium text-white">
                  Ecological constraint
                </div>
              </div>
            </div>

            <div className="mt-7">
              <div className="text-4xl font-semibold tracking-tight text-white">
                Biodiversity
              </div>

              <div className="mt-1 text-4xl font-semibold tracking-tight text-emerald-300">
                pressure
              </div>

              <p className="mt-4 text-sm leading-6 text-slate-500">
                Multiple interacting environmental constraints are increasing
                ecological stress across the assessed site.
              </p>
            </div>

            <div className="mt-6 space-y-2">
              {[
                ["Low soil carbon", "Water retention"],
                ["Low rainfall", "Seasonal stress"],
                ["Monoculture", "Habitat diversity"]
              ].map(([a, b]) => (
                <div
                  key={a}
                  className="flex items-center justify-between rounded-xl border border-white/6 bg-black/10 px-3 py-2.5"
                >
                  <span className="text-xs text-slate-400">{a}</span>
                  <ChevronRight size={13} className="text-slate-700" />
                  <span className="text-xs text-slate-300">{b}</span>
                </div>
              ))}
            </div>

            <div className="mt-5 rounded-xl bg-emerald-400/7 p-3">
              <div className="text-[10px] uppercase tracking-wider text-emerald-300">
                Reasoning confidence
              </div>

              <div className="mt-2 flex items-end gap-2">
                <span className="text-2xl font-semibold text-white">
                  {recommendations.length
                    ? Math.round(
                        recommendations.reduce(
                          (sum, r) => sum + r.confidence,
                          0
                        ) / recommendations.length * 100
                      )
                    : 92}
                  %
                </span>

                <span className="mb-1 text-xs text-slate-600">
                  evidence-supported
                </span>
              </div>
            </div>
          </div>
        </section>

        {/* Reasoning */}
        <section className="rounded-2xl border border-white/7 bg-white/[0.025] p-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                Causal reasoning
              </div>
              <div className="mt-1 text-sm font-medium text-white">
                How the environmental signals interact
              </div>
            </div>

            <div className="hidden items-center gap-2 text-[10px] uppercase tracking-wider text-slate-600 md:flex">
              <Activity size={13} />
              Multi-variable inference
            </div>
          </div>

          <div className="mt-5 grid gap-3 md:grid-cols-4">
            {reasoning.map((step, index) => (
              <div key={step} className="relative">
                <div className="h-full rounded-xl border border-white/7 bg-black/10 p-4">
                  <div className="mb-3 flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-400/10 text-[10px] font-bold text-emerald-300">
                      {index + 1}
                    </span>

                    {index < reasoning.length - 1 && (
                      <ArrowDown
                        size={13}
                        className="text-slate-700 md:hidden"
                      />
                    )}
                  </div>

                  <p className="text-xs leading-5 text-slate-400">
                    {step}
                  </p>
                </div>

                {index < reasoning.length - 1 && (
                  <ArrowUp
                    size={14}
                    className="absolute -right-2 top-1/2 hidden -translate-y-1/2 rotate-90 text-emerald-400/30 md:block"
                  />
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Recommendations */}
        <section className="grid gap-5 lg:grid-cols-[1.4fr_0.6fr]">

          <div>
            <div className="mb-4">
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                Intervention engine
              </div>
              <div className="mt-1 text-lg font-semibold text-white">
                Evidence-backed recommendations
              </div>
            </div>

            <div className="space-y-3">
              {recommendations.length ? (
                recommendations.map((recommendation, index) => (
                  <RecommendationCard
                    key={recommendation.recommendation}
                    recommendation={recommendation}
                    index={index}
                  />
                ))
              ) : (
                <div className="rounded-2xl border border-white/7 bg-white/[0.02] p-6 text-sm text-slate-500">
                  Submit an environmental assessment through the AI assistant
                  to generate site-specific recommendations.
                </div>
              )}
            </div>
          </div>

          {/* Evidence */}
          <div>
            <div className="mb-4">
              <div className="text-[10px] font-bold uppercase tracking-[0.18em] text-emerald-300">
                Knowledge base
              </div>
              <div className="mt-1 text-lg font-semibold text-white">
                Scientific evidence
              </div>
            </div>

            <div className="space-y-2">
              {evidence.length ? (
                evidence.map((item) => (
                  <EvidenceCard key={item.id} evidence={item} />
                ))
              ) : (
                <>
                  <EvidenceCard
                    evidence={{
                      id: "KB-001",
                      source: "FAO",
                      title: "Soil organic carbon and soil biological function"
                    }}
                  />

                  <EvidenceCard
                    evidence={{
                      id: "KB-002",
                      source: "FAO",
                      title: "Cover crops and soil protection"
                    }}
                  />

                  <EvidenceCard
                    evidence={{
                      id: "KB-003",
                      source: "FAO",
                      title: "Agroforestry and biodiversity"
                    }}
                  />
                </>
              )}
            </div>
          </div>
        </section>

        {/* Chat */}
        <section className="overflow-hidden rounded-2xl border border-emerald-400/10 bg-gradient-to-br from-emerald-400/[0.055] to-transparent">
          <div className="border-b border-white/7 px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-400/10">
                <Bot size={17} className="text-emerald-300" />
              </div>

              <div>
                <div className="text-sm font-semibold text-white">
                  Ask Darukaa
                </div>

                <div className="text-xs text-slate-600">
                  Conversational environmental intelligence
                </div>
              </div>
            </div>
          </div>

          <div className="max-h-[360px] space-y-3 overflow-y-auto p-5">
            {!messages.length && (
              <div className="rounded-xl border border-white/6 bg-black/10 p-4">
                <div className="text-xs font-medium text-slate-300">
                  Try asking:
                </div>

                <div className="mt-2 text-sm text-slate-500">
                  "Biodiversity is declining on my farm."
                </div>
              </div>
            )}

            {messages.map((message, index) => (
              <div
                key={index}
                className={`flex ${
                  message.role === "user"
                    ? "justify-end"
                    : "justify-start"
                }`}
              >
                <div
                  className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                    message.role === "user"
                      ? "bg-emerald-400 text-[#06100b]"
                      : "border border-white/7 bg-white/[0.035] text-slate-400"
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex items-center gap-2 text-xs text-slate-600">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-300" />
                Darukaa is reasoning across environmental signals...
              </div>
            )}
          </div>

          <div className="border-t border-white/7 p-4">
            <div className="flex gap-2">
              <input
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") sendMessage()
                }}
                placeholder="Ask about soil, biodiversity, climate or land..."
                className="min-w-0 flex-1 rounded-xl border border-white/8 bg-black/20 px-4 py-3 text-sm text-white outline-none placeholder:text-slate-700 focus:border-emerald-400/30"
              />

              <button
                onClick={sendMessage}
                disabled={loading || !input.trim()}
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-emerald-400 text-[#06100b] transition hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-30"
              >
                <Send size={16} />
              </button>
            </div>
          </div>
        </section>

        {/* Footer */}
        <footer className="flex flex-col justify-between gap-2 border-t border-white/6 py-5 text-[10px] uppercase tracking-wider text-slate-700 sm:flex-row">
          <span>Darukaa.Earth · Environmental Intelligence</span>
          <span>RAG · Structured Reasoning · Scientific Evidence</span>
        </footer>

      </main>
    </div>
  )
}

export default App