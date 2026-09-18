import { useEffect, useRef, useState } from "react"

const API = "http://127.0.0.1:8080"

const CONVERSATION_ID =
  sessionStorage.getItem("darukaa_conversation_id") ||
  (() => {
    const id = `darukaa-${crypto.randomUUID()}`
    sessionStorage.setItem("darukaa_conversation_id", id)
    return id
  })()

/*
  There is no seeded environmental state. The previous version opened
  with invented values (SOC 0.3, rainfall 420 mm) under the ambiguous
  field names `soil_organic_carbon` and `rainfall_mm`, which the
  backend schema now rejects outright. Showing fabricated measurements
  as though they described the user's site is the same class of problem
  as fabricating a citation.
*/

// ---------------------------------------------------------------------
// Ordinal condition scales.
//
// Each derived indicator is plotted against its own reference range,
// the way a lab result is plotted against a normal band. `levels` is
// ordered from best to worst so the marker position carries meaning.
// ---------------------------------------------------------------------
const SCALES = {
  water_stress: {
    label: "Water stress",
    levels: ["low", "moderate", "high"],
    tone: ["favorable", "moderate", "severe"]
  },
  thermal_stress: {
    label: "Thermal stress",
    levels: ["low", "moderate", "high"],
    tone: ["favorable", "moderate", "severe"]
  },
  soil_carbon_condition: {
    label: "Soil carbon",
    levels: ["favorable", "moderate_stress", "high_stress"],
    tone: ["favorable", "moderate", "severe"]
  },
  soil_ph_condition: {
    label: "Soil pH",
    levels: ["favorable", "moderate_stress", "high_stress"],
    tone: ["favorable", "moderate", "severe"]
  },
  habitat_condition: {
    label: "Habitat",
    levels: ["favorable", "reduced"],
    tone: ["favorable", "severe"]
  },
  land_cover_pressure: {
    label: "Land-cover pressure",
    levels: ["low", "moderate", "high"],
    tone: ["favorable", "moderate", "severe"]
  },
  biodiversity_evidence_confidence: {
    label: "Survey coverage",
    levels: ["high", "moderate", "low", "none"],
    tone: ["favorable", "moderate", "severe", "severe"]
  }
}

const TONE_VAR = {
  favorable: "var(--favorable)",
  moderate: "var(--moderate)",
  severe: "var(--severe)",
  unknown: "var(--unknown)"
}

const UNITS = {
  soil_organic_carbon_g_per_kg: "g/kg",
  precipitation_mm_day: "mm/day",
  soil_moisture: "%",
  temperature_c: "\u00B0C",
  soil_ph: "",
  species_richness: "species",
  latitude: "\u00B0",
  longitude: "\u00B0"
}

const FIELD_NAMES = {
  soil_organic_carbon_g_per_kg: "Soil organic carbon",
  precipitation_mm_day: "Precipitation",
  soil_ph: "Soil pH",
  soil_moisture: "Soil moisture",
  temperature_c: "Temperature",
  land_use: "Land use",
  crop: "Crop",
  region: "Climate region",
  species_richness: "Species observed",
  latitude: "Latitude",
  longitude: "Longitude",
  habitat_diversity: "Habitat diversity",
  pollution_level: "Pollution",
  deforestation_level: "Deforestation"
}

const readable = (value) =>
  String(value ?? "").replace(/_/g, " ")

const ordinal = (n) => {
  const remainder = n % 100
  if (remainder >= 10 && remainder <= 20) return `${n}th`
  const suffix = { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"
  return `${n}${suffix}`
}

// ---------------------------------------------------------------------
function Rule({ className = "" }) {
  return (
    <div
      className={"h-px w-full " + className}
      style={{ background: "var(--rule)" }}
    />
  )
}

function SectionHeading({ children, note }) {
  return (
    <div className="mb-4 flex items-baseline justify-between gap-4">
      <h2 className="text-[15px] font-semibold tracking-tight">
        {children}
      </h2>
      {note && (
        <span
          className="text-xs"
          style={{ color: "var(--ink-faint)" }}
        >
          {note}
        </span>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------
// The signature element: an indicator plotted on its reference range.
// ---------------------------------------------------------------------
function ConditionScale({ scale, value }) {
  const index = scale.levels.indexOf(String(value))
  const known = index >= 0
  const tone = known ? scale.tone[index] : "unknown"
  const color = TONE_VAR[tone]

  return (
    <div className="py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13px]">{scale.label}</span>
        <span
          className="text-[13px] font-medium"
          style={{ color }}
        >
          {known ? readable(value) : "not measured"}
        </span>
      </div>

      <div
        className="mt-2 flex gap-1"
        role="img"
        aria-label={`${scale.label}: ${
          known ? readable(value) : "not measured"
        }`}
      >
        {scale.levels.map((level, position) => {
          const active = known && position === index
          const passed = known && position < index

          return (
            <div
              key={level}
              className="h-1.5 flex-1 rounded-[1px]"
              style={{
                background: active
                  ? color
                  : passed
                    ? "var(--rule)"
                    : "var(--rule-soft)"
              }}
            />
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------
// Observations, with provenance. A value from SoilGrids must not look
// like a value the user measured themselves.
// ---------------------------------------------------------------------
function ObservationRecord({ variables, provenance, notes, referenceContext }) {
  const entries = Object.entries(variables || {}).filter(
    ([key]) => key !== "latitude" && key !== "longitude"
  )

  const sources = provenance?.field_sources || {}
  const referenceFields = referenceContext?.fields || {}

  if (!entries.length) {
    return (
      <p
        className="text-[13px] leading-6"
        style={{ color: "var(--ink-soft)" }}
      >
        No observations recorded yet. Describe the site below, or give
        coordinates and the record fills from NASA POWER, SoilGrids,
        WorldCover and GBIF.
      </p>
    )
  }

  return (
    <div>
      <div className="space-y-0">
        {entries.map(([key, value], position) => {
          const source = sources[key]
          const unit = UNITS[key]
          const numeric = typeof value === "number"

          return (
            <div key={key}>
              {position > 0 && (
                <Rule className="opacity-40" />
              )}
              <div className="flex items-baseline justify-between gap-4 py-2.5">
                <div className="min-w-0">
                  <div className="text-[13px]">
                    {FIELD_NAMES[key] || readable(key)}
                  </div>
                  <div
                    className="text-[11px]"
                    style={{ color: "var(--ink-faint)" }}
                  >
                    {source
                      ? `retrieved from ${source}`
                      : "your observation"}
                  </div>
                </div>

                <div className="shrink-0 text-right">
                  <div
                    className={
                      "text-[13px] " + (numeric ? "measure" : "")
                    }
                  >
                    {numeric ? value : readable(value)}
                    {unit && (
                      <span
                        className="ml-1 text-[11px]"
                        style={{ color: "var(--ink-faint)" }}
                      >
                        {unit}
                      </span>
                    )}
                  </div>

                  {referenceFields[key] && (
                    <div
                      className="text-[11px]"
                      style={{ color: "var(--ink-faint)" }}
                      title={referenceFields[key].note}
                    >
                      {ordinal(
                        Math.round(referenceFields[key].percentile)
                      )}{" "}
                      pct. of {referenceFields[key].reference_n} ref.
                      sites
                    </div>
                  )}
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {notes?.length > 0 && (
        <ul className="mt-4 space-y-1.5">
          {notes.map((note) => (
            <li
              key={note}
              className="text-[11px] leading-5"
              style={{ color: "var(--ink-faint)" }}
            >
              {note}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------
function GeographicContext({ variables, provenance }) {
  const { latitude, longitude } = variables || {}
  if (latitude == null || longitude == null) return null

  const retrieved = provenance?.retrieved_live || []
  const degraded = provenance?.degraded_sources || []

  return (
    <div
      className="mt-5 border-t pt-4"
      style={{ borderColor: "var(--rule)" }}
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-[13px]">Location</span>
        <span className="measure text-[13px]">
          {Number(latitude).toFixed(4)},{" "}
          {Number(longitude).toFixed(4)}
        </span>
      </div>

      {retrieved.map((source) => (
        <div key={source.source} className="mt-3">
          <div className="flex items-baseline justify-between gap-3">
            <span className="text-[12px]">{source.source}</span>
            <span
              className="text-[11px]"
              style={{ color: "var(--ink-faint)" }}
            >
              {(source.variables || [])
                .map((name) => FIELD_NAMES[name] || readable(name))
                .join(", ")}
            </span>
          </div>
          <p
            className="mt-1 text-[11px] leading-5"
            style={{ color: "var(--ink-faint)" }}
          >
            {source.caveat}
          </p>
        </div>
      ))}

      {degraded.map((failure) => (
        <p
          key={failure.source}
          className="mt-3 text-[11px] leading-5"
          style={{ color: "var(--severe)" }}
        >
          {failure.source} did not respond, so its variables are
          missing from this record. {failure.reason}
        </p>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------
// A recommendation. Ordered by confidence, so the numbering encodes a
// real ranking rather than decoration.
// ---------------------------------------------------------------------
function Finding({ finding, position }) {
  const [openFactors, setOpenFactors] = useState(false)

  const evidenceTone =
    finding.evidence_status === "supported"
      ? "favorable"
      : finding.evidence_status === "weak"
        ? "moderate"
        : "unknown"

  return (
    <article className="py-7">
      <div className="grid gap-6 md:grid-cols-[2.5rem_1fr]">
        <div
          className="measure pt-0.5 text-[13px]"
          style={{ color: "var(--ink-faint)" }}
        >
          {String(position).padStart(2, "0")}
        </div>

        <div className="min-w-0">
          <h3 className="max-w-[62ch] text-[17px] font-semibold leading-7 tracking-tight">
            {finding.recommendation}
          </h3>

          <p
            className="mt-3 max-w-[70ch] text-[14px] leading-7"
            style={{ color: "var(--ink-soft)" }}
          >
            {finding.why_it_works}
          </p>

          {finding.expected_change && (
            <p
              className="mt-2 max-w-[70ch] text-[13px] leading-6"
              style={{ color: "var(--ink-faint)" }}
            >
              {finding.expected_change}
            </p>
          )}

          <dl className="mt-5 grid gap-x-8 gap-y-4 sm:grid-cols-3">
            <div>
              <dt
                className="text-[11px]"
                style={{ color: "var(--ink-faint)" }}
              >
                Affects
              </dt>
              <dd className="mt-1 text-[13px] leading-6">
                {finding.impacted_metrics.join(", ")}
              </dd>
            </div>

            <div>
              <dt
                className="text-[11px]"
                style={{ color: "var(--ink-faint)" }}
              >
                Time horizon
              </dt>
              <dd className="mt-1 text-[13px] leading-6">
                {finding.time_horizon}
              </dd>
            </div>

            <div>
              <dt
                className="text-[11px]"
                style={{ color: "var(--ink-faint)" }}
              >
                {finding.confidence_label || "Prototype confidence"}
              </dt>
              <dd className="mt-1 flex items-baseline gap-2">
                <span className="measure text-[13px]">
                  {Math.round(finding.confidence * 100)}%
                </span>
                <button
                  type="button"
                  onClick={() => setOpenFactors((open) => !open)}
                  className="text-[12px] underline underline-offset-2"
                  style={{ color: "var(--ink-faint)" }}
                >
                  {openFactors ? "Hide how" : "How this was scored"}
                </button>
              </dd>
            </div>
          </dl>

          {openFactors && (
            <div
              className="record-in mt-4 border-l pl-4"
              style={{ borderColor: "var(--rule)" }}
            >
              {finding.confidence_caveat && (
                <p
                  className="max-w-[70ch] text-[12px] leading-6"
                  style={{ color: "var(--ink-soft)" }}
                >
                  {finding.confidence_caveat}
                </p>
              )}

              <div className="mt-3 space-y-2">
                {(finding.confidence_factors || []).map((factor) => (
                  <div
                    key={factor.name}
                    className="flex items-baseline justify-between gap-4"
                  >
                    <span
                      className="max-w-[56ch] text-[12px] leading-5"
                      style={{ color: "var(--ink-soft)" }}
                    >
                      {factor.detail}
                    </span>
                    <span
                      className="measure shrink-0 text-[12px]"
                      style={{ color: "var(--ink-faint)" }}
                    >
                      {factor.value.toFixed(2)} &times;{" "}
                      {factor.weight.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>

              {finding.limiting_factor && (
                <p
                  className="mt-3 max-w-[70ch] text-[12px] leading-6"
                  style={{ color: "var(--ink-faint)" }}
                >
                  Most limiting: {finding.limiting_factor}
                </p>
              )}
            </div>
          )}

          <div
            className="mt-5 border-t pt-4"
            style={{ borderColor: "var(--rule-soft)" }}
          >
            <div
              className="text-[11px]"
              style={{ color: TONE_VAR[evidenceTone] }}
            >
              {finding.evidence_status === "supported"
                ? "Supporting evidence"
                : finding.evidence_status === "weak"
                  ? "Partially relevant evidence"
                  : "No qualifying evidence"}
            </div>

            {finding.evidence?.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {finding.evidence.map((item) => (
                  <li
                    key={item.id}
                    className="flex items-baseline justify-between gap-4"
                  >
                    <a
                      href={`${API}/knowledge/${item.id}`}
                      target="_blank"
                      rel="noreferrer"
                      className="max-w-[62ch] text-[13px] leading-6 underline underline-offset-2"
                    >
                      {item.title}
                      <span
                        className="ml-2 text-[11px] no-underline"
                        style={{ color: "var(--ink-faint)" }}
                      >
                        {item.source}
                        {item.year ? `, ${item.year}` : ""}
                      </span>
                    </a>
                    <span
                      className="measure shrink-0 text-[11px]"
                      style={{ color: "var(--ink-faint)" }}
                    >
                      {item.relevance?.toFixed(2)}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <p
                className="mt-2 max-w-[70ch] text-[13px] leading-6"
                style={{ color: "var(--ink-soft)" }}
              >
                {finding.evidence_note}
              </p>
            )}
          </div>
        </div>
      </div>
    </article>
  )
}

// ---------------------------------------------------------------------
function Conversation({
  messages,
  input,
  setInput,
  onSend,
  loading,
  missing
}) {
  const endRef = useRef(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest" })
  }, [messages, loading])

  return (
    <div>
      <div className="max-h-[22rem] space-y-4 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <p
            className="text-[13px] leading-7"
            style={{ color: "var(--ink-soft)" }}
          >
            Describe the site in your own words. Units are converted
            and reported back, so &ldquo;0.58% SOC&rdquo; and
            &ldquo;600 mm annual rainfall&rdquo; are both understood.
            Values already given are remembered between messages.
          </p>
        )}

        {messages.map((message, index) => (
          <div key={index}>
            <div
              className="text-[11px]"
              style={{ color: "var(--ink-faint)" }}
            >
              {message.role === "user" ? "You" : "Assessment"}
            </div>
            <p className="mt-1 max-w-[64ch] text-[13px] leading-6">
              {message.content}
            </p>
          </div>
        ))}

        {loading && (
          <p
            className="text-[13px]"
            style={{ color: "var(--ink-faint)" }}
          >
            Reasoning and retrieving evidence&hellip;
          </p>
        )}

        <div ref={endRef} />
      </div>

      {missing?.length > 0 && (
        <p
          className="mt-4 text-[12px] leading-6"
          style={{ color: "var(--moderate)" }}
        >
          Still needed: {missing.map(readable).join(", ")}
        </p>
      )}

      <div
        className="mt-4 border-t pt-4"
        style={{ borderColor: "var(--rule)" }}
      >
        <textarea
          value={input}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault()
              onSend()
            }
          }}
          rows={3}
          placeholder="My SOC is 0.58%, annual rainfall is 600 mm, pH is 5.4 and this is wheat monoculture."
          className="w-full resize-none rounded-sm border bg-transparent p-3 text-[13px] leading-6 placeholder:opacity-45"
          style={{ borderColor: "var(--rule)" }}
        />

        <button
          type="button"
          onClick={onSend}
          disabled={loading || !input.trim()}
          className="mt-3 rounded-sm px-4 py-2 text-[13px] font-medium disabled:opacity-40"
          style={{ background: "var(--ink)", color: "var(--panel)" }}
        >
          {loading ? "Assessing" : "Assess site"}
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------
function Panel({ children, className = "" }) {
  return (
    <section
      className={"rounded-sm border p-6 " + className}
      style={{
        borderColor: "var(--rule)",
        background: "var(--panel)"
      }}
    >
      {children}
    </section>
  )
}

// ---------------------------------------------------------------------
export default function App() {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [analysis, setAnalysis] = useState(null)
  const [variables, setVariables] = useState({})
  const [missing, setMissing] = useState([])
  const [mergeNotes, setMergeNotes] = useState([])

  const sendMessage = async () => {
    if (!input.trim() || loading) return

    const message = input.trim()
    setInput("")
    setMessages((prev) => [
      ...prev,
      { role: "user", content: message }
    ])
    setLoading(true)

    try {
      const response = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          conversation_id: CONVERSATION_ID,
          message
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = await response.json()

      setVariables(data.environment || {})
      setMissing(data.missing_variables || [])
      setMergeNotes(data.normalization_notes || [])

      if (data.type === "analysis") {
        setAnalysis(data.analysis)
      }

      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: data.message }
      ])
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            `The analysis engine did not respond (${error.message}). ` +
            `Start the backend with: uvicorn app.main:app --port 8080`
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  const derived = analysis?.derived_features || null
  const findings = analysis?.recommendations || []
  const provenance = analysis?.data_provenance || null

  return (
    <div className="min-h-screen">
      <header
        className="border-b"
        style={{ borderColor: "var(--rule)" }}
      >
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-baseline justify-between gap-3 px-6 py-5">
          <div className="flex items-baseline gap-3">
            <span className="text-[15px] font-semibold tracking-tight">
              Darukaa.Earth
            </span>
            <span
              className="text-[13px]"
              style={{ color: "var(--ink-faint)" }}
            >
              Environmental assessment record
            </span>
          </div>

          <span
            className="text-[12px]"
            style={{ color: "var(--ink-faint)" }}
          >
            Prototype. Findings are not validated ecological
            predictions.
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1180px] px-6 py-8">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          {/* Observations and conversation */}
          <Panel>
            <SectionHeading
              note={
                provenance?.live_enrichment_succeeded
                  ? "measured and retrieved"
                  : undefined
              }
            >
              Observations
            </SectionHeading>

            <ObservationRecord
              variables={variables}
              provenance={provenance}
              notes={mergeNotes}
              referenceContext={
                derived?.reference_dataset_context
              }
            />

            <GeographicContext
              variables={variables}
              provenance={provenance}
            />

            <div
              className="mt-6 border-t pt-6"
              style={{ borderColor: "var(--rule)" }}
            >
              <Conversation
                messages={messages}
                input={input}
                setInput={setInput}
                onSend={sendMessage}
                loading={loading}
                missing={missing}
              />
            </div>
          </Panel>

          {/* Condition readout */}
          <Panel className="h-fit">
            <SectionHeading note="derived">Condition</SectionHeading>

            {derived ? (
              <div className="record-in divide-y" style={{ borderColor: "var(--rule-soft)" }}>
                {Object.entries(SCALES).map(([key, scale]) => (
                  <ConditionScale
                    key={key}
                    scale={scale}
                    value={derived[key]}
                  />
                ))}
              </div>
            ) : (
              <p
                className="text-[13px] leading-6"
                style={{ color: "var(--ink-soft)" }}
              >
                Indicators appear once an assessment runs.
              </p>
            )}

            {derived && (
              <p
                className="mt-5 max-w-[46ch] text-[11px] leading-5"
                style={{ color: "var(--ink-faint)" }}
              >
                Indicators are computed from prototype thresholds. They
                describe conditions, not ecological outcomes.
              </p>
            )}

            {analysis?.biodiversity_observation_note && (
              <p
                className="mt-3 max-w-[46ch] text-[11px] leading-5"
                style={{ color: "var(--ink-faint)" }}
              >
                {analysis.biodiversity_observation_note}
              </p>
            )}
          </Panel>
        </div>

        {/* Reasoning */}
        {analysis?.reasoning_chain?.length > 0 && (
          <Panel className="record-in mt-6">
            <SectionHeading note="how the variables interact">
              Reasoning
            </SectionHeading>

            <ol className="space-y-3">
              {analysis.reasoning_chain.map((step, index) => (
                <li
                  key={index}
                  className="max-w-[78ch] text-[14px] leading-7"
                  style={{ color: "var(--ink-soft)" }}
                >
                  {step}
                </li>
              ))}
            </ol>
          </Panel>
        )}

        {/* Findings */}
        {findings.length > 0 && (
          <section className="record-in mt-6">
            <div className="mb-1 flex items-baseline justify-between gap-4">
              <h2 className="text-[15px] font-semibold tracking-tight">
                Recommended interventions
              </h2>
              <span
                className="text-[12px]"
                style={{ color: "var(--ink-faint)" }}
              >
                ranked by prototype confidence
              </span>
            </div>

            <Rule />

            <div
              className="divide-y"
              style={{ borderColor: "var(--rule)" }}
            >
              {findings.map((finding, index) => (
                <Finding
                  key={finding.rule_id || index}
                  finding={finding}
                  position={index + 1}
                />
              ))}
            </div>
          </section>
        )}

        {/* Caveats */}
        {analysis?.caveats?.length > 0 && (
          <section
            className="mt-8 border-t pt-6"
            style={{ borderColor: "var(--rule)" }}
          >
            <h2 className="text-[13px] font-semibold">
              What this assessment cannot tell you
            </h2>

            <ul className="mt-3 space-y-2">
              {analysis.caveats.map((caveat) => (
                <li
                  key={caveat}
                  className="max-w-[78ch] text-[12px] leading-6"
                  style={{ color: "var(--ink-soft)" }}
                >
                  {caveat}
                </li>
              ))}
            </ul>
          </section>
        )}
      </main>
    </div>
  )
}
