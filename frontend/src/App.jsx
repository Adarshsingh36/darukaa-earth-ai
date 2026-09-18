import { useMemo, useState } from "react"
import "./App.css"

const API = "http://127.0.0.1:8000"

const CONVERSATION_ID =
  sessionStorage.getItem("darukaa_conversation_id") ||
  (() => {
    const id = `darukaa-${crypto.randomUUID()}`
    sessionStorage.setItem("darukaa_conversation_id", id)
    return id
  })()

const format = (value, digits = 1) =>
  typeof value === "number" ? value.toFixed(digits) : "—"

function MetricCard({ icon, label, value, unit, tone }) {
  return (
    <div className="metric-card">
      <div className="metric-top">
        <span className="metric-icon">{icon}</span>
        {tone && <span className={`metric-badge ${tone}`}>{tone}</span>}
      </div>
      <div className="metric-label">{label}</div>
      <div className="metric-value">
        {value ?? "—"}
        {unit && <span>{unit}</span>}
      </div>
    </div>
  )
}

function Signal({ label, value, tone = "neutral" }) {
  return (
    <div className="signal">
      <span>{label}</span>
      <strong className={tone}>{value || "—"}</strong>
    </div>
  )
}

function MapPanel({ variables }) {
  const lat = variables?.latitude
  const lon = variables?.longitude

  return (
    <div className="map-panel">
      <div className="map-grid">
        <div className="map-orbit orbit-one" />
        <div className="map-orbit orbit-two" />
        <div className="map-orbit orbit-three" />
        <div className="map-center-glow" />

        {lat != null && lon != null ? (
          <div className="map-pin">
            <span />
          </div>
        ) : (
          <div className="map-empty">
            <span>⌖</span>
            Coordinates not provided
          </div>
        )}
      </div>

      <div className="map-footer">
        <div>
          <small>LOCATION</small>
          <strong>
            {lat != null && lon != null
              ? `${Number(lat).toFixed(4)}, ${Number(lon).toFixed(4)}`
              : "Awaiting coordinates"}
          </strong>
        </div>
        <div className="data-layer">
          <small>DATA LAYERS</small>
          <strong>6 environmental signals</strong>
        </div>
      </div>
    </div>
  )
}

function AssessmentPanel({ analysis }) {
  if (!analysis) {
    return (
      <div className="assessment-panel">
        <div className="assessment-icon">✦</div>
        <div className="eyebrow">AI ASSESSMENT</div>
        <h2>Awaiting<br /><em>site intelligence</em></h2>
        <p>
          Describe the site or provide coordinates to activate
          environmental reasoning.
        </p>
        <div className="empty-assessment">
          Multi-metric reasoning offline until assessment runs.
        </div>
      </div>
    )
  }

  const derived = analysis.derived_features || {}
  const pressure = derived.total_environmental_pressure || 0
  const condition = derived.environmental_condition || "unknown"

  const title =
    pressure >= 2
      ? "Biodiversity pressure"
      : derived.habitat_pressure
        ? "Habitat pressure"
        : "Ecological condition"

  return (
    <div className="assessment-panel">
      <div className="assessment-icon">✦</div>
      <div className="eyebrow">AI ASSESSMENT</div>

      <h2>
        {title.split(" ")[0]}<br />
        <em>{title.split(" ").slice(1).join(" ")}</em>
      </h2>

      <p>
        {pressure > 0
          ? "Land-use pressure is interacting with habitat structure across the assessed site."
          : "Measured environmental conditions are currently within the prototype's favorable ranges."}
      </p>

      <div className="assessment-signals">
        <Signal
          label="Habitat condition"
          value={derived.habitat_condition}
          tone={derived.habitat_condition === "reduced" ? "warning" : "good"}
        />
        <Signal
          label="Land-cover pressure"
          value={derived.land_cover_pressure}
          tone={derived.land_cover_pressure === "high" ? "danger" : "warning"}
        />
        <Signal
          label="Biodiversity signal"
          value={derived.biodiversity_observation_signal}
          tone="good"
        />
      </div>

      <div className="confidence-box">
        <div>
          <small>REASONING CONFIDENCE</small>
          <strong>
            {analysis.recommendations?.[0]?.confidence
              ? `${Math.round(analysis.recommendations[0].confidence * 100)}%`
              : "—"}
          </strong>
        </div>
        <span>evidence-supported</span>
      </div>

      <div className="condition-caption">
        Current classification: <strong>{condition.replaceAll("_", " ")}</strong>
      </div>
    </div>
  )
}

function Recommendation({ finding, index }) {
  return (
    <article className="recommendation">
      <div className="recommendation-number">
        {String(index + 1).padStart(2, "0")}
      </div>

      <div className="recommendation-body">
        <div className="recommendation-header">
          <div>
            <div className="eyebrow">RECOMMENDED INTERVENTION</div>
            <h3>{finding.recommendation}</h3>
          </div>

          <div className="confidence-pill">
            {Math.round((finding.confidence || 0) * 100)}%
            <span>confidence</span>
          </div>
        </div>

        <p className="why">
          {finding.why_it_works}
        </p>

        <div className="recommendation-meta">
          <div>
            <small>IMPACTED METRICS</small>
            <strong>
              {(finding.impacted_metrics || []).join(" · ")}
            </strong>
          </div>

          <div>
            <small>TIME HORIZON</small>
            <strong>{finding.time_horizon || "Not specified"}</strong>
          </div>

          <div>
            <small>EXPECTED CHANGE</small>
            <strong>{finding.expected_change || "Directional improvement"}</strong>
          </div>
        </div>

        {finding.evidence?.length > 0 && (
          <div className="evidence">
            <small>EVIDENCE FROM KNOWLEDGE BASE</small>

            {finding.evidence.map((item) => (
              <div className="evidence-item" key={item.id}>
                <span className="evidence-dot" />
                <div>
                  <strong>{item.title}</strong>
                  <span>
                    {item.source} · {item.year || "n.d."}
                  </span>
                </div>
                <b>{item.relevance?.toFixed(2)}</b>
              </div>
            ))}
          </div>
        )}
      </div>
    </article>
  )
}

export default function App() {
  const [input, setInput] = useState("")
  const [messages, setMessages] = useState([])
  const [variables, setVariables] = useState({})
  const [analysis, setAnalysis] = useState(null)
  const [missing, setMissing] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState("")

  const derived = analysis?.derived_features || {}
  const findings = analysis?.recommendations || []
  const provenance = analysis?.data_provenance || {}

  const metrics = useMemo(
    () => [
      {
        icon: "◌",
        label: "Soil organic carbon",
        value:
          variables.soil_organic_carbon_g_per_kg != null
            ? format(variables.soil_organic_carbon_g_per_kg, 1)
            : null,
        unit: "g/kg",
        tone: derived.soil_carbon_condition === "favorable" ? "good" : "low"
      },
      {
        icon: "◈",
        label: "Soil pH",
        value:
          variables.soil_ph != null ? format(variables.soil_ph, 1) : null,
        unit: "",
        tone: derived.soil_ph_condition === "favorable" ? "good" : "moderate"
      },
      {
        icon: "⌁",
        label: "Precipitation",
        value:
          variables.precipitation_mm_day != null
            ? format(variables.precipitation_mm_day, 2)
            : null,
        unit: "mm/day",
        tone: derived.water_stress || "neutral"
      },
      {
        icon: "♨",
        label: "Temperature",
        value:
          variables.temperature_c != null
            ? format(variables.temperature_c, 1)
            : null,
        unit: "°C",
        tone: derived.thermal_stress || "neutral"
      }
    ],
    [variables, derived]
  )

  async function sendMessage() {
    const message = input.trim()
    if (!message || loading) return

    setInput("")
    setError("")
    setLoading(true)

    setMessages((prev) => [
      ...prev,
      { role: "user", content: message }
    ])

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
        throw new Error(`API returned HTTP ${response.status}`)
      }

      const data = await response.json()

      setVariables(data.environment || {})
      setMissing(data.missing_variables || [])

      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: data.message
        }
      ])

      if (data.type === "analysis") {
        setAnalysis(data.analysis)
      }
    } catch (err) {
      setError(err.message)
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            "The intelligence engine could not complete the assessment. Make sure the FastAPI backend is running on port 8000."
        }
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">♧</div>
          <div>
            <div className="brand-name">
              DARUKAA<span>.EARTH</span>
            </div>
            <div className="brand-subtitle">
              ENVIRONMENTAL INTELLIGENCE
            </div>
          </div>
        </div>

        <div className="online-status">
          <span />
          INTELLIGENCE ENGINE ONLINE
        </div>
      </header>

      <main className="dashboard">
        <div className="workspace-label">
          <span>⌖</span> Environmental assessment workspace
        </div>

        <section className="hero">
          <div>
            <h1>
              Ecosystem intelligence <em>in context.</em>
            </h1>
            <p>
              Connect soil, climate, land-use and biodiversity signals
              to uncover ecological constraints and evidence-backed
              interventions.
            </p>
          </div>

          <div className="mode-card">
            <small>ASSESSMENT MODE</small>
            <strong>Multi-metric reasoning</strong>
          </div>
        </section>

        <section className="top-grid">
          <div className="panel site-profile">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">SITE PROFILE</div>
                <h2>Current environmental state</h2>
              </div>
              <div className="panel-symbol">≋</div>
            </div>

            <div className="metric-grid">
              {metrics.map((metric) => (
                <MetricCard key={metric.label} {...metric} />
              ))}
            </div>

            <div className="land-card">
              <div>
                <small>LAND USE</small>
                <strong>
                  {variables.land_use
                    ? String(variables.land_use)
                        .replaceAll("_", " ")
                        .replace(/\b\w/g, (c) => c.toUpperCase())
                    : "Awaiting assessment"}
                </strong>
              </div>

              {variables.region && (
                <span>{String(variables.region).replaceAll("_", " ")}</span>
              )}

              {derived.management_intensity && (
                <div className="management">
                  Management intensity:{" "}
                  <strong>{derived.management_intensity}</strong>
                </div>
              )}
            </div>

            {variables.species_richness != null && (
              <div className="species-row">
                <span>OBSERVED SPECIES</span>
                <strong>{variables.species_richness}</strong>
                <small>
                  GBIF observation proxy · not a complete census
                </small>
              </div>
            )}
          </div>

          <div className="panel spatial-panel">
            <div className="panel-heading">
              <div>
                <div className="eyebrow">SPATIAL CONTEXT</div>
                <h2>Environmental site</h2>
              </div>
            </div>

            <MapPanel variables={variables} />

            <div className="source-row">
              {["NASA POWER", "SoilGrids", "WorldCover", "GBIF"].map(
                (source) => (
                  <span key={source}>
                    <i />
                    {source}
                  </span>
                )
              )}
            </div>
          </div>

          <AssessmentPanel analysis={analysis} />
        </section>

        <section className="conversation-section panel">
          <div className="section-title">
            <div>
              <div className="eyebrow">ENVIRONMENTAL QUERY</div>
              <h2>Talk to the intelligence engine</h2>
            </div>

            {missing.length > 0 && (
              <div className="missing">
                Still needed: {missing.join(", ").replaceAll("_", " ")}
              </div>
            )}
          </div>

          <div className="conversation">
            {messages.length === 0 && (
              <div className="conversation-empty">
                <span>01</span>
                <p>
                  Describe the site naturally. Include coordinates,
                  soil, rainfall, land use or biodiversity observations.
                  The engine will ask for missing variables and remember
                  information across turns.
                </p>
              </div>
            )}

            {messages.map((message, index) => (
              <div className={`message ${message.role}`} key={index}>
                <small>
                  {message.role === "user" ? "YOU" : "DARUKAA ENGINE"}
                </small>
                <p>{message.content}</p>
              </div>
            ))}

            {loading && (
              <div className="message assistant">
                <small>DARUKAA ENGINE</small>
                <p className="thinking">
                  <span /> Combining environmental signals and retrieving
                  evidence...
                </p>
              </div>
            )}
          </div>

          <div className="query-box">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault()
                  sendMessage()
                }
              }}
              placeholder="e.g. The land is intensively farmed. Soil carbon is 0.3%, rainfall is 420 mm and the region is semi-arid..."
            />
            <button onClick={sendMessage} disabled={loading || !input.trim()}>
              {loading ? "ANALYSING..." : "ASSESS SITE →"}
            </button>
          </div>

          {error && <div className="error">{error}</div>}
        </section>

        {analysis?.reasoning_chain?.length > 0 && (
          <section className="reasoning-section panel">
            <div className="section-title">
              <div>
                <div className="eyebrow">REASONING TRACE</div>
                <h2>How the variables interact</h2>
              </div>
              <span className="trace-label">DATA → FEATURES → REASONING → EVIDENCE</span>
            </div>

            <div className="reasoning-chain">
              {analysis.reasoning_chain.map((step, index) => (
                <div className="reasoning-step" key={index}>
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <p>{step}</p>
                  {index < analysis.reasoning_chain.length - 1 && (
                    <b>→</b>
                  )}
                </div>
              ))}
            </div>
          </section>
        )}

        {findings.length > 0 && (
          <section className="recommendations">
            <div className="recommendation-heading">
              <div>
                <div className="eyebrow">AI-GENERATED INTERVENTIONS</div>
                <h2>Recommended actions</h2>
              </div>
              <span>
                {findings.length} evidence-backed intervention
                {findings.length !== 1 ? "s" : ""}
              </span>
            </div>

            {findings.map((finding, index) => (
              <Recommendation
                finding={finding}
                index={index}
                key={finding.rule_id || index}
              />
            ))}
          </section>
        )}

        {analysis && (
          <footer className="data-footer">
            <div>
              <strong>LIVE DATA PIPELINE</strong>
              <span>
                {provenance.live_enrichment_succeeded
                  ? "Live geospatial enrichment succeeded"
                  : "Degraded enrichment"}
              </span>
            </div>

            <div>
              <strong>PROVENANCE</strong>
              <span>
                NASA POWER · ISRIC SoilGrids · ESA WorldCover · GBIF
              </span>
            </div>

            <div>
              <strong>PROTOTYPE STATUS</strong>
              <span>Findings are not validated ecological predictions.</span>
            </div>
          </footer>
        )}
      </main>
    </div>
  )
}
