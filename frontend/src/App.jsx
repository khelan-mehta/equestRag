import React, {
  useState,
  useEffect,
  useRef,
  useCallback,
  useMemo,
} from "react";
import {
  Upload,
  Send,
  Trash2,
  Download,
  FileText,
  BarChart3,
  MessageSquare,
  Search,
  Brain,
  Loader2,
  Key,
  Zap,
  Building2,
  Thermometer,
  DollarSign,
  TrendingUp,
  AlertCircle,
  CheckCircle,
  X,
  ChevronDown,
  ChevronRight,
  Activity,
  Menu,
  PanelLeftClose,
  Sparkles,
  Copy,
  Check,
} from "lucide-react";
import {
  PieChart,
  Pie,
  Cell,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  AreaChart,
  Area,
} from "recharts";

const API_BASE_URL = import.meta.env.VITE_API_URL || "/api";

const CHART_COLORS = [
  "#6366f1",
  "#f59e0b",
  "#ef4444",
  "#10b981",
  "#3b82f6",
  "#8b5cf6",
  "#f97316",
  "#14b8a6",
];

const METRIC_ICONS = {
  eui: Zap,
  total_kwh: Activity,
  floor_area_sqft: Building2,
  peak_cooling_kbtu_h: Thermometer,
  peak_cooling_tons: Thermometer,
  peak_heating_kbtu_h: Thermometer,
  cost_per_sqft: DollarSign,
  total_annual_cost: DollarSign,
  avg_power_kw: Zap,
  total_gas_therm: Activity,
};

const METRIC_LABELS = {
  eui: "Energy Use Intensity",
  total_kwh: "Total Electricity",
  floor_area_sqft: "Floor Area",
  peak_cooling_kbtu_h: "Peak Cooling",
  peak_cooling_tons: "Peak Cooling",
  peak_heating_kbtu_h: "Peak Heating",
  cost_per_sqft: "Cost / sqft",
  total_annual_cost: "Annual Cost",
  avg_power_kw: "Avg Power",
  total_gas_therm: "Total Gas",
};

const METRIC_UNITS = {
  eui: "kWh/sqft/yr",
  total_kwh: "kWh",
  floor_area_sqft: "sqft",
  peak_cooling_kbtu_h: "kBTU/h",
  peak_cooling_tons: "tons",
  peak_heating_kbtu_h: "kBTU/h",
  cost_per_sqft: "$/sqft/yr",
  total_annual_cost: "$",
  avg_power_kw: "kW",
  total_gas_therm: "therms",
};

function formatNumber(val) {
  if (typeof val !== "number") return val;
  if (Math.abs(val) >= 1_000_000) return `${(val / 1_000_000).toFixed(2)}M`;
  if (Math.abs(val) >= 1_000) return `${(val / 1_000).toFixed(1)}k`;
  return val % 1 === 0 ? val.toLocaleString() : val.toFixed(2);
}

// ── Markdown / LLM Output Parser ──────────────────────────────────
// Parses common LLM output patterns: headers, bold, italic, code blocks,
// inline code, lists, tables, and horizontal rules into React elements.

function ParsedMarkdown({ content }) {
  const blocks = useMemo(() => parseBlocks(content), [content]);
  return <div className="space-y-2">{blocks}</div>;
}

function parseBlocks(text) {
  if (!text) return null;
  const lines = text.split("\n");
  const elements = [];
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    if (line.trimStart().startsWith("```")) {
      const lang = line.trimStart().slice(3).trim();
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trimStart().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      elements.push(
        <CodeBlock key={key++} code={codeLines.join("\n")} language={lang} />,
      );
      continue;
    }

    // Table detection (line with | separators)
    if (line.includes("|") && line.trim().startsWith("|")) {
      const tableLines = [];
      while (
        i < lines.length &&
        lines[i].includes("|") &&
        lines[i].trim().startsWith("|")
      ) {
        tableLines.push(lines[i]);
        i++;
      }
      if (tableLines.length >= 2) {
        elements.push(<MarkdownTable key={key++} lines={tableLines} />);
        continue;
      }
      // fallback: not really a table
      i -= tableLines.length;
    }

    // Heading
    const headingMatch = line.match(/^(#{1,4})\s+(.+)/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const text = headingMatch[2];
      const Tag = `h${Math.min(level + 1, 6)}`; // offset so # => h2 in chat context
      const sizes = {
        2: "text-base font-bold",
        3: "text-sm font-bold",
        4: "text-sm font-semibold",
        5: "text-sm font-medium",
        6: "text-sm font-medium",
      };
      elements.push(
        <Tag
          key={key++}
          className={`${sizes[Math.min(level + 1, 6)] || "text-sm font-semibold"} text-slate-800 mt-3 mb-1`}
        >
          {renderInline(text)}
        </Tag>,
      );
      i++;
      continue;
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line.trim())) {
      elements.push(<hr key={key++} className="border-slate-200 my-2" />);
      i++;
      continue;
    }

    // Unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      elements.push(
        <ul
          key={key++}
          className="list-disc list-inside space-y-1 text-sm text-slate-700 ml-1"
        >
          {listItems.map((item, j) => (
            <li key={j} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ul>,
      );
      continue;
    }

    // Ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const listItems = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        listItems.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      elements.push(
        <ol
          key={key++}
          className="list-decimal list-inside space-y-1 text-sm text-slate-700 ml-1"
        >
          {listItems.map((item, j) => (
            <li key={j} className="leading-relaxed">
              {renderInline(item)}
            </li>
          ))}
        </ol>,
      );
      continue;
    }

    // Blockquote
    if (line.trimStart().startsWith(">")) {
      const quoteLines = [];
      while (i < lines.length && lines[i].trimStart().startsWith(">")) {
        quoteLines.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      elements.push(
        <blockquote
          key={key++}
          className="border-l-3 border-indigo-400 pl-3 py-1 text-sm text-slate-600 italic bg-indigo-50/40 rounded-r-lg"
        >
          {renderInline(quoteLines.join(" "))}
        </blockquote>,
      );
      continue;
    }

    // Empty line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Regular paragraph — collect consecutive non-special lines
    const paraLines = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !lines[i].trimStart().startsWith("```") &&
      !lines[i].match(/^#{1,4}\s+/) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !lines[i].trimStart().startsWith(">") &&
      !/^(-{3,}|\*{3,}|_{3,})$/.test(lines[i].trim()) &&
      !(lines[i].includes("|") && lines[i].trim().startsWith("|"))
    ) {
      paraLines.push(lines[i]);
      i++;
    }
    if (paraLines.length > 0) {
      elements.push(
        <p key={key++} className="text-sm text-slate-800 leading-relaxed">
          {renderInline(paraLines.join(" "))}
        </p>,
      );
    }
  }

  return elements;
}

// Inline formatting: **bold**, *italic*, `code`, [links](url)
function renderInline(text) {
  if (!text) return null;
  // Split by patterns, preserving delimiters
  const tokens = [];
  // Regex to match: **bold**, *italic*, `code`, [text](url)
  const regex = /(\*\*(.+?)\*\*|\*(.+?)\*|`([^`]+)`|\[([^\]]+)\]\(([^)]+)\))/g;
  let lastIndex = 0;
  let match;

  while ((match = regex.exec(text)) !== null) {
    // Text before match
    if (match.index > lastIndex) {
      tokens.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      // **bold**
      tokens.push(
        <strong key={match.index} className="font-semibold text-slate-900">
          {match[2]}
        </strong>,
      );
    } else if (match[3]) {
      // *italic*
      tokens.push(
        <em key={match.index} className="italic">
          {match[3]}
        </em>,
      );
    } else if (match[4]) {
      // `code`
      tokens.push(
        <code
          key={match.index}
          className="px-1.5 py-0.5 bg-slate-100 text-indigo-700 rounded text-xs font-mono"
        >
          {match[4]}
        </code>,
      );
    } else if (match[5] && match[6]) {
      // [text](url)
      tokens.push(
        <a
          key={match.index}
          href={match[6]}
          target="_blank"
          rel="noopener noreferrer"
          className="text-indigo-600 underline underline-offset-2 hover:text-indigo-800"
        >
          {match[5]}
        </a>,
      );
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    tokens.push(text.slice(lastIndex));
  }

  return tokens.length === 0 ? text : tokens;
}

// ── Code Block with copy ──────────────────────────────────────────
function CodeBlock({ code, language }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <div className="rounded-lg overflow-hidden border border-slate-200 bg-slate-900 my-2">
      <div className="flex items-center justify-between px-3 py-1.5 bg-slate-800 text-xs text-slate-400">
        <span>{language || "code"}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 hover:text-slate-200 transition-colors"
        >
          {copied ? (
            <>
              <Check size={12} /> Copied
            </>
          ) : (
            <>
              <Copy size={12} /> Copy
            </>
          )}
        </button>
      </div>
      <pre className="p-3 overflow-x-auto text-xs leading-relaxed">
        <code className="text-slate-100 font-mono">{code}</code>
      </pre>
    </div>
  );
}

// ── Markdown Table ────────────────────────────────────────────────
function MarkdownTable({ lines }) {
  const parseRow = (line) =>
    line
      .split("|")
      .map((c) => c.trim())
      .filter((c) => c !== "");

  const headers = parseRow(lines[0]);
  // Skip separator line (index 1 if it's dashes)
  const isSep = (line) => /^[\s|:-]+$/.test(line);
  const dataStart = lines.length > 1 && isSep(lines[1]) ? 2 : 1;
  const rows = lines.slice(dataStart).map(parseRow);

  return (
    <div className="overflow-x-auto my-2 rounded-lg border border-slate-200">
      <table className="min-w-full text-sm">
        <thead>
          <tr className="bg-slate-50">
            {headers.map((h, i) => (
              <th
                key={i}
                className="px-3 py-2 text-left text-xs font-semibold text-slate-600 border-b border-slate-200"
              >
                {renderInline(h)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className={i % 2 === 0 ? "bg-white" : "bg-slate-50/50"}>
              {row.map((cell, j) => (
                <td
                  key={j}
                  className="px-3 py-2 text-slate-700 border-b border-slate-100"
                >
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Notification ──────────────────────────────────────────────────
function Notification({ notification, onClose }) {
  if (!notification) return null;
  const styles = {
    success: "bg-emerald-50 border-emerald-400 text-emerald-800",
    error: "bg-rose-50 border-rose-400 text-rose-800",
    info: "bg-sky-50 border-sky-400 text-sky-800",
  };
  const icons = { success: CheckCircle, error: AlertCircle, info: AlertCircle };
  const Icon = icons[notification.type] || AlertCircle;
  return (
    <div
      className={`fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg border shadow-lg max-w-md animate-in ${styles[notification.type]}`}
    >
      <Icon size={18} className="flex-shrink-0" />
      <span className="text-sm font-medium flex-1">{notification.message}</span>
      <button
        onClick={onClose}
        className="flex-shrink-0 opacity-60 hover:opacity-100"
      >
        <X size={16} />
      </button>
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────
function App() {
  const [sessionId, setSessionId] = useState(null);
  const [activeTab, setActiveTab] = useState("chat");
  const [files, setFiles] = useState({});
  const [additionalDocs, setAdditionalDocs] = useState([]);
  const [processing, setProcessing] = useState(false);
  const [processProgress, setProcessProgress] = useState(0);
  const [apiKey, setApiKey] = useState("");
  const [chatHistory, setChatHistory] = useState([]);
  const [chatInput, setChatInput] = useState("");
  const [buildingData, setBuildingData] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [searchExplanation, setSearchExplanation] = useState("");
  const [searchExplaining, setSearchExplaining] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [notification, setNotification] = useState(null);
  const [apiKeyVisible, setApiKeyVisible] = useState(false);
  const [filesProcessed, setFilesProcessed] = useState([]);

  const chatEndRef = useRef(null);
  const notifTimeout = useRef(null);

  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, loading]);

  const notify = useCallback((type, message) => {
    if (notifTimeout.current) clearTimeout(notifTimeout.current);
    setNotification({ type, message });
    notifTimeout.current = setTimeout(() => setNotification(null), 5000);
  }, []);

  const apiFetch = useCallback(
    async (path, options = {}) => {
      const headers = { ...options.headers };
      if (sessionId) headers["X-Session-ID"] = sessionId;
      return fetch(`${API_BASE_URL}${path}`, { ...options, headers });
    },
    [sessionId],
  );

  // ── File Handling ─────────────────────────────────────────
  const fileTypes = [
    { key: "ps_e", label: "PS-E (All Fuel Meters)", accept: ".txt,.pdf" },
    { key: "ps_e2", label: "PS-E2 (Electric Meters)", accept: ".txt,.pdf" },
    { key: "bepu", label: "BEPU (Building Performance)", accept: ".txt,.pdf" },
    { key: "ls_c", label: "LS-C (Peak Loads)", accept: ".txt,.pdf" },
    { key: "es_d", label: "ES-D (Energy Cost)", accept: ".txt,.pdf" },
    { key: "lv_d", label: "LV-D (Building Envelope)", accept: ".txt,.pdf" },
  ];

  const handleFileChange = (key, e) => {
    const file = e.target.files[0];
    if (file) setFiles((prev) => ({ ...prev, [key]: file }));
  };

  const handleAdditionalDocs = (e) => {
    if (e.target.files?.length) setAdditionalDocs(Array.from(e.target.files));
  };

  const totalFiles =
    Object.keys(files).length + (additionalDocs.length > 0 ? 1 : 0);

  // ── Process ───────────────────────────────────────────────
  const processFiles = async () => {
    if (totalFiles === 0) return;
    setProcessing(true);
    setProcessProgress(10);

    const formData = new FormData();
    Object.entries(files).forEach(([key, file]) => {
      if (file) formData.append(key, file);
    });
    additionalDocs.forEach((file) => formData.append("additional_docs", file));
    if (apiKey) formData.append("api_key", apiKey);

    try {
      setProcessProgress(30);
      const headers = {};
      if (sessionId) headers["X-Session-ID"] = sessionId;

      const res = await fetch(`${API_BASE_URL}/process`, {
        method: "POST",
        body: formData,
        headers,
      });
      setProcessProgress(70);

      if (!res.ok) throw new Error(`Server error (${res.status})`);
      const data = await res.json();
      setProcessProgress(90);

      if (data.success) {
        setSessionId(data.session_id);
        setBuildingData(data.building_data);
        setMetrics(data.metrics);
        setFilesProcessed(data.files_processed || []);
        setProcessProgress(100);
        notify(
          "success",
          `Processed ${data.files_processed?.length || 0} files with ${data.num_chunks} chunks`,
        );
      } else {
        throw new Error(data.error || "Processing failed");
      }
    } catch (err) {
      notify("error", `Processing failed: ${err.message}`);
    } finally {
      setTimeout(() => {
        setProcessing(false);
        setProcessProgress(0);
      }, 600);
    }
  };

  // ── Chat ──────────────────────────────────────────────────
  const sendMessage = async (overrideMsg) => {
    const msg = overrideMsg || chatInput.trim();
    if (!msg) return;
    setChatInput("");
    setChatHistory((prev) => [
      ...prev,
      { type: "user", content: msg, timestamp: new Date() },
    ]);
    setLoading(true);

    try {
      const res = await apiFetch("/query", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: msg, api_key: apiKey }),
      });
      const data = await res.json();

      if (data.success) {
        setChatHistory((prev) => [
          ...prev,
          {
            type: "assistant",
            content: data.response,
            sources: data.sources,
            timestamp: new Date(),
          },
        ]);
      } else {
        throw new Error(data.error);
      }
    } catch (err) {
      setChatHistory((prev) => [
        ...prev,
        { type: "error", content: err.message, timestamp: new Date() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  // ── Search with LLM Explanation ───────────────────────────
  const searchDocuments = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    setSearchExplanation("");
    setSearchResults([]);

    try {
      const res = await apiFetch("/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery }),
      });
      const data = await res.json();
      const results = data.results || [];
      setSearchResults(results);

      // If we have results, ask the LLM to explain/synthesize them
      if (results.length > 0) {
        setSearchExplaining(true);
        try {
          const synthesisPrompt = buildSearchSynthesisPrompt(
            searchQuery,
            results,
          );
          const llmRes = await apiFetch("/query", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: synthesisPrompt, api_key: apiKey }),
          });
          const llmData = await llmRes.json();
          if (llmData.success) {
            setSearchExplanation(llmData.response);
          }
        } catch {
          // Silently fail — raw results are still shown
        } finally {
          setSearchExplaining(false);
        }
      }
    } catch (err) {
      notify("error", `Search failed: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  function buildSearchSynthesisPrompt(query, results) {
    const snippets = results
      .map(
        (r, i) =>
          `[Document ${i + 1}: ${r.filename} (${r.type}, relevance: ${(r.score * 100).toFixed(1)}%)]\n${r.text}`,
      )
      .join("\n\n");

    return (
      `Based on the following retrieved document excerpts, provide a concise, helpful synthesis that directly answers or addresses the user's search query.\n\n` +
      `**User's query:** "${query}"\n\n` +
      `**Retrieved excerpts:**\n${snippets}\n\n` +
      `Instructions: Synthesize the key findings from these documents. Highlight the most relevant information, note any important values or metrics mentioned, and explain how the documents relate to the query. ` +
      `If the excerpts contain contradictory or complementary information, point that out. Be concise but thorough. Use markdown formatting for clarity.`
    );
  }

  // ── Export ────────────────────────────────────────────────
  const exportData = async (format) => {
    try {
      const res = await apiFetch(`/export/${format}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });
      if (format === "json") {
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        downloadBlob(blob, `equest_analysis_${Date.now()}.json`);
      } else {
        const blob = await res.blob();
        downloadBlob(blob, `equest_report_${Date.now()}.pdf`);
      }
      notify("success", `${format.toUpperCase()} exported successfully`);
    } catch (err) {
      notify("error", `Export failed: ${err.message}`);
    }
  };

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ── Chart data ────────────────────────────────────────────
  const chartData = useMemo(() => {
    if (!buildingData) return {};
    const charts = {};

    for (const key of ["ps_e", "ps_e2"]) {
      if (Array.isArray(buildingData[key])) {
        const rows = buildingData[key];
        charts.monthly = rows.filter((r) => r.Month !== "ANNUAL");
        const annual = rows.find((r) => r.Month === "ANNUAL");
        if (annual) {
          charts.endUse = [
            { name: "Lighting", value: annual.Lights || 0 },
            { name: "Equipment", value: annual.Equipment || 0 },
            { name: "Heating", value: annual.Heating || 0 },
            { name: "Cooling", value: annual.Cooling || 0 },
            { name: "Ventilation", value: annual.Vent_Fans || 0 },
            { name: "Hot Water", value: annual.Hot_Water || 0 },
          ].filter((d) => d.value > 0);
        }
        break;
      }
    }

    if (buildingData.ls_c) {
      charts.peakLoads = [
        { name: "Cooling", value: buildingData.ls_c.cooling_load_kbtu_h || 0 },
        { name: "Heating", value: buildingData.ls_c.heating_load_kbtu_h || 0 },
      ].filter((d) => d.value > 0);
    }

    if (buildingData.bepu?.eui_kwh_sqft_yr) {
      charts.euiBenchmark = [
        { name: "This Building", value: buildingData.bepu.eui_kwh_sqft_yr },
        { name: "Excellent", value: 12 },
        { name: "Good", value: 18 },
        { name: "Average", value: 25 },
      ];
    }

    return charts;
  }, [buildingData]);

  const exampleQuestions = [
    "What is the building's Energy Use Intensity (EUI)?",
    "What are the peak cooling and heating loads?",
    "Show me the energy breakdown by end-use category",
    "What are the annual energy costs for this building?",
    "Which month has the highest energy consumption?",
  ];

  const tabs = [
    { id: "chat", label: "AI Chat", icon: MessageSquare },
    { id: "viz", label: "Visualizations", icon: BarChart3 },
    { id: "metrics", label: "Metrics", icon: Activity },
    { id: "search", label: "Search", icon: Search },
  ];

  return (
    <div className="flex h-screen bg-slate-50 overflow-hidden">
      <Notification
        notification={notification}
        onClose={() => setNotification(null)}
      />

      {/* ── Sidebar ───────────────────────────────────────── */}
      <aside
        className={`${sidebarOpen ? "w-80" : "w-0"} bg-slate-900 text-white flex flex-col transition-all duration-300 overflow-hidden flex-shrink-0`}
      >
        <div className="p-5 border-b border-slate-700/50">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-600 flex items-center justify-center">
              <Brain size={20} />
            </div>
            <div>
              <h1 className="text-lg font-bold tracking-tight">eQuest RAG</h1>
              <p className="text-xs text-slate-400">Energy Analysis Platform</p>
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-5">
          {/* API Key */}
          <div>
            <button
              onClick={() => setApiKeyVisible(!apiKeyVisible)}
              className="flex items-center justify-between w-full text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2"
            >
              <span className="flex items-center gap-1.5">
                <Key size={12} /> OpenAI API Key
              </span>
              {apiKeyVisible ? (
                <ChevronDown size={14} />
              ) : (
                <ChevronRight size={14} />
              )}
            </button>
            {apiKeyVisible && (
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-sm text-white placeholder-slate-500 focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none"
              />
            )}
          </div>

          {/* File Uploads */}
          <div>
            <p className="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-3">
              eQuest Reports
            </p>
            <div className="space-y-2.5">
              {fileTypes.map(({ key, label, accept }) => (
                <div key={key}>
                  <label className="block text-xs text-slate-300 mb-1 font-medium">
                    {label}
                  </label>
                  <label
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-xs transition-colors ${
                      files[key]
                        ? "bg-emerald-900/40 border border-emerald-700/50 text-emerald-300"
                        : "bg-slate-800 border border-slate-700 text-slate-400 hover:border-slate-600"
                    }`}
                  >
                    {files[key] ? (
                      <>
                        <CheckCircle
                          size={14}
                          className="text-emerald-400 flex-shrink-0"
                        />
                        <span className="truncate">{files[key].name}</span>
                      </>
                    ) : (
                      <>
                        <Upload size={14} className="flex-shrink-0" />
                        <span>Choose file...</span>
                      </>
                    )}
                    <input
                      type="file"
                      accept={accept}
                      onChange={(e) => handleFileChange(key, e)}
                      className="hidden"
                    />
                  </label>
                </div>
              ))}

              <div>
                <label className="block text-xs text-slate-300 mb-1 font-medium">
                  Additional Documents
                </label>
                <label
                  className={`flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer text-xs transition-colors ${
                    additionalDocs.length > 0
                      ? "bg-emerald-900/40 border border-emerald-700/50 text-emerald-300"
                      : "bg-slate-800 border border-slate-700 text-slate-400 hover:border-slate-600"
                  }`}
                >
                  {additionalDocs.length > 0 ? (
                    <>
                      <CheckCircle
                        size={14}
                        className="text-emerald-400 flex-shrink-0"
                      />
                      <span>{additionalDocs.length} file(s) selected</span>
                    </>
                  ) : (
                    <>
                      <Upload size={14} className="flex-shrink-0" />
                      <span>Choose files...</span>
                    </>
                  )}
                  <input
                    type="file"
                    accept=".pdf,.txt"
                    multiple
                    onChange={handleAdditionalDocs}
                    className="hidden"
                  />
                </label>
              </div>
            </div>
          </div>

          <button
            onClick={processFiles}
            disabled={processing || totalFiles === 0}
            className="w-full py-3 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700 disabled:text-slate-500 text-white rounded-lg font-semibold text-sm transition-colors flex items-center justify-center gap-2 relative overflow-hidden"
          >
            {processing ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                Processing... {processProgress}%
                <div
                  className="absolute bottom-0 left-0 h-1 bg-indigo-400 transition-all duration-300"
                  style={{ width: `${processProgress}%` }}
                />
              </>
            ) : (
              <>
                <Upload size={16} /> Process{" "}
                {totalFiles > 0
                  ? `${totalFiles} File${totalFiles > 1 ? "s" : ""}`
                  : "Files"}
              </>
            )}
          </button>

          {buildingData && (
            <div className="p-3 bg-emerald-900/30 border border-emerald-800/50 rounded-lg">
              <p className="text-sm font-medium text-emerald-300 flex items-center gap-2">
                <CheckCircle size={14} /> Data Loaded
              </p>
              <p className="text-xs text-emerald-400/80 mt-1">
                {filesProcessed.length} reports &middot;{" "}
                {Object.keys(metrics || {}).length} metrics
              </p>
            </div>
          )}
        </div>

        {buildingData && (
          <div className="p-4 border-t border-slate-700/50 space-y-2">
            <button
              onClick={() => exportData("json")}
              className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <Download size={14} /> Export JSON
            </button>
            <button
              onClick={() => exportData("pdf")}
              className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded-lg text-sm font-medium flex items-center justify-center gap-2 transition-colors"
            >
              <FileText size={14} /> Generate PDF Report
            </button>
          </div>
        )}
      </aside>

      {/* ── Main Content ──────────────────────────────────── */}
      <main className="flex-1 flex flex-col min-w-0">
        <header className="bg-white border-b border-slate-200 px-4 py-2 flex items-center gap-4 flex-shrink-0">
          <button
            onClick={() => setSidebarOpen(!sidebarOpen)}
            className="p-2 rounded-lg hover:bg-slate-100 text-slate-600"
          >
            {sidebarOpen ? <PanelLeftClose size={18} /> : <Menu size={18} />}
          </button>
          <nav className="flex gap-1">
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`px-4 py-2 rounded-lg text-sm font-medium flex items-center gap-2 transition-colors ${
                  activeTab === id
                    ? "bg-indigo-600 text-white shadow-sm"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon size={16} />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </nav>
          <div className="flex-1" />
          {sessionId && (
            <span className="text-xs text-slate-400 hidden md:block">
              Session: {sessionId.substring(0, 8)}
            </span>
          )}
        </header>

        <div className="flex-1 overflow-y-auto">
          {/* ── Chat Tab ──────────────────────────── */}
          {activeTab === "chat" && (
            <div className="h-full flex flex-col max-w-4xl mx-auto w-full">
              {!buildingData ? (
                <div className="flex-1 flex items-center justify-center p-8">
                  <div className="text-center max-w-md">
                    <div className="w-16 h-16 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
                      <Brain size={32} className="text-slate-400" />
                    </div>
                    <h2 className="text-xl font-semibold text-slate-800 mb-2">
                      Upload eQuest Files
                    </h2>
                    <p className="text-slate-500">
                      Upload your eQuest simulation reports to start analyzing
                      building energy performance with AI.
                    </p>
                  </div>
                </div>
              ) : (
                <>
                  <div className="flex-1 overflow-y-auto p-6 space-y-4">
                    {chatHistory.length === 0 && (
                      <div className="space-y-3">
                        <p className="text-sm font-medium text-slate-500 mb-3">
                          Try asking:
                        </p>
                        <div className="grid gap-2">
                          {exampleQuestions.map((q, i) => (
                            <button
                              key={i}
                              onClick={() => sendMessage(q)}
                              className="text-left px-4 py-3 rounded-lg border border-slate-200 hover:border-indigo-300 hover:bg-indigo-50/50 text-sm text-slate-700 transition-colors"
                            >
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    {chatHistory.map((msg, idx) => (
                      <div
                        key={idx}
                        className={`flex gap-3 ${msg.type === "user" ? "justify-end" : "justify-start"}`}
                      >
                        {msg.type !== "user" && (
                          <div
                            className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                              msg.type === "error"
                                ? "bg-rose-100"
                                : "bg-indigo-600"
                            }`}
                          >
                            {msg.type === "error" ? (
                              <AlertCircle
                                size={16}
                                className="text-rose-600"
                              />
                            ) : (
                              <Brain size={16} className="text-white" />
                            )}
                          </div>
                        )}
                        <div
                          className={`max-w-[75%] rounded-xl px-4 py-3 ${
                            msg.type === "user"
                              ? "bg-indigo-600 text-white"
                              : msg.type === "error"
                                ? "bg-rose-50 border border-rose-200 text-rose-800"
                                : "bg-white border border-slate-200 text-slate-800"
                          }`}
                        >
                          {/* Use parsed markdown for assistant messages, plain for user */}
                          {msg.type === "user" ? (
                            <div className="text-sm whitespace-pre-wrap leading-relaxed">
                              {msg.content}
                            </div>
                          ) : msg.type === "error" ? (
                            <div className="text-sm whitespace-pre-wrap leading-relaxed">
                              {msg.content}
                            </div>
                          ) : (
                            <ParsedMarkdown content={msg.content} />
                          )}
                          {msg.sources?.length > 0 && (
                            <div className="mt-2 pt-2 border-t border-slate-200/60">
                              <p className="text-xs text-slate-500 mb-1">
                                Sources:
                              </p>
                              <div className="flex flex-wrap gap-1">
                                {msg.sources.map((s, i) => (
                                  <span
                                    key={i}
                                    className="text-xs bg-slate-100 text-slate-600 px-2 py-0.5 rounded"
                                  >
                                    {s}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    ))}

                    {loading && (
                      <div className="flex gap-3">
                        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
                          <Loader2
                            size={16}
                            className="text-white animate-spin"
                          />
                        </div>
                        <div className="bg-white border border-slate-200 rounded-xl px-4 py-3">
                          <div className="flex items-center gap-2 text-sm text-slate-500">
                            <span className="inline-block w-2 h-2 bg-indigo-500 rounded-full animate-pulse" />
                            Analyzing...
                          </div>
                        </div>
                      </div>
                    )}
                    <div ref={chatEndRef} />
                  </div>

                  <div className="p-4 border-t border-slate-200 bg-white">
                    <div className="flex gap-2 max-w-4xl mx-auto">
                      <input
                        type="text"
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={(e) =>
                          e.key === "Enter" && !e.shiftKey && sendMessage()
                        }
                        placeholder="Ask about your building's energy performance..."
                        className="flex-1 px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none text-sm"
                      />
                      <button
                        onClick={() => sendMessage()}
                        disabled={loading || !chatInput.trim()}
                        className="px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                      >
                        <Send size={16} />
                      </button>
                      {chatHistory.length > 0 && (
                        <button
                          onClick={() => setChatHistory([])}
                          className="px-3 py-2.5 bg-slate-100 text-slate-500 rounded-lg hover:bg-slate-200 transition-colors"
                          title="Clear chat"
                        >
                          <Trash2 size={16} />
                        </button>
                      )}
                    </div>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── Visualizations Tab ────────────────── */}
          {activeTab === "viz" && (
            <div className="p-6 max-w-7xl mx-auto">
              {!buildingData ? (
                <EmptyState
                  icon={BarChart3}
                  title="No Data Available"
                  desc="Process eQuest files to view energy visualizations."
                />
              ) : Object.keys(chartData).length === 0 ? (
                <EmptyState
                  icon={BarChart3}
                  title="No Chart Data"
                  desc="Upload PS-E, BEPU, or LS-C reports to generate visualizations."
                />
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {chartData.endUse && (
                    <ChartCard title="Annual Energy by End-Use">
                      <ResponsiveContainer width="100%" height={300}>
                        <PieChart>
                          <Pie
                            data={chartData.endUse}
                            dataKey="value"
                            nameKey="name"
                            cx="50%"
                            cy="50%"
                            innerRadius={60}
                            outerRadius={110}
                            paddingAngle={2}
                            label={({ name, percent }) =>
                              `${name} ${(percent * 100).toFixed(0)}%`
                            }
                          >
                            {chartData.endUse.map((_, i) => (
                              <Cell
                                key={i}
                                fill={CHART_COLORS[i % CHART_COLORS.length]}
                              />
                            ))}
                          </Pie>
                          <Tooltip
                            formatter={(val) =>
                              `${Number(val).toLocaleString()}`
                            }
                          />
                        </PieChart>
                      </ResponsiveContainer>
                    </ChartCard>
                  )}

                  {chartData.monthly && (
                    <ChartCard title="Monthly Energy Consumption">
                      <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={chartData.monthly}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#e2e8f0"
                          />
                          <XAxis dataKey="Month" tick={{ fontSize: 12 }} />
                          <YAxis tick={{ fontSize: 12 }} />
                          <Tooltip
                            formatter={(val) =>
                              `${Number(val).toLocaleString()}`
                            }
                          />
                          <Bar
                            dataKey="Total"
                            fill="#6366f1"
                            radius={[4, 4, 0, 0]}
                          />
                        </BarChart>
                      </ResponsiveContainer>
                    </ChartCard>
                  )}

                  {chartData.monthly && (
                    <ChartCard title="Monthly Energy Breakdown">
                      <ResponsiveContainer width="100%" height={300}>
                        <AreaChart data={chartData.monthly}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#e2e8f0"
                          />
                          <XAxis dataKey="Month" tick={{ fontSize: 12 }} />
                          <YAxis tick={{ fontSize: 12 }} />
                          <Tooltip
                            formatter={(val) =>
                              `${Number(val).toLocaleString()}`
                            }
                          />
                          <Legend />
                          <Area
                            type="monotone"
                            dataKey="Cooling"
                            stackId="1"
                            stroke="#6366f1"
                            fill="#6366f1"
                            fillOpacity={0.6}
                          />
                          <Area
                            type="monotone"
                            dataKey="Heating"
                            stackId="1"
                            stroke="#ef4444"
                            fill="#ef4444"
                            fillOpacity={0.6}
                          />
                          <Area
                            type="monotone"
                            dataKey="Lights"
                            stackId="1"
                            stroke="#f59e0b"
                            fill="#f59e0b"
                            fillOpacity={0.6}
                          />
                          <Area
                            type="monotone"
                            dataKey="Equipment"
                            stackId="1"
                            stroke="#10b981"
                            fill="#10b981"
                            fillOpacity={0.6}
                          />
                          <Area
                            type="monotone"
                            dataKey="Vent_Fans"
                            stackId="1"
                            stroke="#3b82f6"
                            fill="#3b82f6"
                            fillOpacity={0.6}
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </ChartCard>
                  )}

                  {chartData.peakLoads && (
                    <ChartCard title="Peak Load Comparison (kBTU/h)">
                      <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={chartData.peakLoads}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#e2e8f0"
                          />
                          <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                          <YAxis tick={{ fontSize: 12 }} />
                          <Tooltip
                            formatter={(val) =>
                              `${Number(val).toLocaleString()} kBTU/h`
                            }
                          />
                          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                            {chartData.peakLoads.map((_, i) => (
                              <Cell
                                key={i}
                                fill={i === 0 ? "#3b82f6" : "#ef4444"}
                              />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </ChartCard>
                  )}

                  {chartData.euiBenchmark && (
                    <ChartCard title="EUI Benchmark Comparison">
                      <ResponsiveContainer width="100%" height={300}>
                        <BarChart data={chartData.euiBenchmark}>
                          <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#e2e8f0"
                          />
                          <XAxis dataKey="name" tick={{ fontSize: 11 }} />
                          <YAxis
                            tick={{ fontSize: 12 }}
                            label={{
                              value: "kWh/sqft/yr",
                              angle: -90,
                              position: "insideLeft",
                              style: { fontSize: 11 },
                            }}
                          />
                          <Tooltip
                            formatter={(val) =>
                              `${Number(val).toFixed(2)} kWh/sqft/yr`
                            }
                          />
                          <Bar dataKey="value" radius={[6, 6, 0, 0]}>
                            {chartData.euiBenchmark.map((_, i) => (
                              <Cell
                                key={i}
                                fill={
                                  i === 0
                                    ? "#6366f1"
                                    : [
                                        "#10b981",
                                        "#f59e0b",
                                        "#f97316",
                                        "#ef4444",
                                      ][i - 1] || "#94a3b8"
                                }
                              />
                            ))}
                          </Bar>
                        </BarChart>
                      </ResponsiveContainer>
                    </ChartCard>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Metrics Tab ───────────────────────── */}
          {activeTab === "metrics" && (
            <div className="p-6 max-w-7xl mx-auto">
              {!metrics || Object.keys(metrics).length === 0 ? (
                <EmptyState
                  icon={Activity}
                  title="No Metrics Available"
                  desc="Process eQuest files to view building performance metrics."
                />
              ) : (
                <div className="space-y-6">
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                    {Object.entries(metrics).map(([key, value]) => {
                      const Icon = METRIC_ICONS[key] || Activity;
                      const label =
                        METRIC_LABELS[key] || key.replace(/_/g, " ");
                      const unit = METRIC_UNITS[key] || "";
                      return (
                        <div
                          key={key}
                          className="bg-white rounded-xl border border-slate-200 p-5 shadow-sm hover:shadow-md transition-shadow"
                        >
                          <div className="flex items-center gap-3 mb-3">
                            <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center">
                              <Icon size={18} className="text-indigo-600" />
                            </div>
                            <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                              {label}
                            </p>
                          </div>
                          <p className="text-2xl font-bold text-slate-800">
                            {key.includes("cost") && "$"}
                            {formatNumber(value)}
                          </p>
                          {unit && (
                            <p className="text-xs text-slate-400 mt-1">
                              {unit}
                            </p>
                          )}
                        </div>
                      );
                    })}
                  </div>

                  {buildingData && (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                      {buildingData.bepu &&
                        typeof buildingData.bepu === "object" &&
                        !Array.isArray(buildingData.bepu) && (
                          <DataSection
                            title="Building Performance (BEPU)"
                            data={buildingData.bepu}
                          />
                        )}
                      {buildingData.ls_c &&
                        typeof buildingData.ls_c === "object" &&
                        !Array.isArray(buildingData.ls_c) && (
                          <DataSection
                            title="Peak Loads (LS-C)"
                            data={buildingData.ls_c}
                          />
                        )}
                      {buildingData.es_d &&
                        typeof buildingData.es_d === "object" &&
                        !Array.isArray(buildingData.es_d) && (
                          <DataSection
                            title="Energy Costs (ES-D)"
                            data={buildingData.es_d}
                          />
                        )}
                      {buildingData.metadata &&
                        typeof buildingData.metadata === "object" && (
                          <DataSection
                            title="Project Metadata"
                            data={buildingData.metadata}
                          />
                        )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ── Search Tab (Enhanced with LLM synthesis) ──── */}
          {activeTab === "search" && (
            <div className="p-6 max-w-4xl mx-auto space-y-4">
              <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-6">
                <h2 className="text-lg font-semibold text-slate-800 mb-4">
                  Document Search
                </h2>
                <div className="flex gap-2 mb-6">
                  <input
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && searchDocuments()}
                    placeholder="Search across all uploaded documents..."
                    className="flex-1 px-4 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none text-sm"
                  />
                  <button
                    onClick={searchDocuments}
                    disabled={loading || !searchQuery.trim()}
                    className="px-5 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-500 disabled:opacity-40 transition-colors flex items-center gap-2 text-sm font-medium"
                  >
                    {loading ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Search size={16} />
                    )}
                    Search
                  </button>
                </div>

                {!buildingData && (
                  <p className="text-sm text-slate-500 text-center py-8">
                    Process files to enable document search.
                  </p>
                )}
              </div>

              {/* LLM Synthesis Card */}
              {(searchExplaining || searchExplanation) && (
                <div className="bg-gradient-to-br from-indigo-50 to-white rounded-xl border border-indigo-200 shadow-sm p-5">
                  <div className="flex items-center gap-2 mb-3">
                    <div className="w-7 h-7 rounded-lg bg-indigo-600 flex items-center justify-center">
                      <Sparkles size={14} className="text-white" />
                    </div>
                    <h3 className="text-sm font-semibold text-indigo-900">
                      AI Analysis of Results
                    </h3>
                  </div>
                  {searchExplaining ? (
                    <div className="flex items-center gap-2 text-sm text-indigo-600 py-4">
                      <Loader2 size={16} className="animate-spin" />
                      Synthesizing search results...
                    </div>
                  ) : (
                    <ParsedMarkdown content={searchExplanation} />
                  )}
                </div>
              )}

              {/* Raw Results */}
              {searchResults.length > 0 && (
                <div className="space-y-3">
                  <h3 className="text-sm font-semibold text-slate-600 flex items-center gap-2">
                    <FileText size={14} />
                    Retrieved Documents ({searchResults.length})
                  </h3>
                  {searchResults.map((result, idx) => (
                    <div
                      key={idx}
                      className="bg-white border border-slate-200 rounded-lg p-4 hover:border-slate-300 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded">
                            {result.type}
                          </span>
                          <span className="text-sm font-medium text-slate-700">
                            {result.filename}
                          </span>
                        </div>
                        <span
                          className={`text-xs font-medium px-2 py-0.5 rounded ${
                            result.score > 0.7
                              ? "bg-emerald-100 text-emerald-700"
                              : result.score > 0.4
                                ? "bg-amber-100 text-amber-700"
                                : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {(result.score * 100).toFixed(1)}% match
                        </span>
                      </div>
                      <p className="text-sm text-slate-600 leading-relaxed">
                        {result.text}
                      </p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ── Shared Components ──────────────────────────────────────────────

function EmptyState({ icon: Icon, title, desc }) {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="text-center max-w-sm">
        <div className="w-14 h-14 bg-slate-100 rounded-2xl flex items-center justify-center mx-auto mb-4">
          <Icon size={28} className="text-slate-400" />
        </div>
        <h3 className="text-lg font-semibold text-slate-700 mb-1">{title}</h3>
        <p className="text-sm text-slate-500">{desc}</p>
      </div>
    </div>
  );
}

function ChartCard({ title, children }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <h3 className="text-sm font-semibold text-slate-700 mb-4">{title}</h3>
      {children}
    </div>
  );
}

function DataSection({ title, data }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm p-5">
      <h3 className="text-sm font-semibold text-slate-700 mb-3">{title}</h3>
      <div className="divide-y divide-slate-100">
        {Object.entries(data).map(([key, value]) => (
          <div key={key} className="flex justify-between py-2 text-sm">
            <span className="text-slate-500">
              {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
            </span>
            <span className="font-medium text-slate-800">
              {typeof value === "number"
                ? value.toLocaleString()
                : String(value)}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default App;
