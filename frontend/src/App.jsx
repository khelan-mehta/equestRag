import React, { useState, useEffect, useRef, useCallback } from "react";
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
  Sun,
  Moon,
  Activity,
  Zap,
  DollarSign,
  Thermometer,
  Wind,
  Building2,
  ChevronDown,
  X,
  CheckCircle2,
  AlertCircle,
  Info,
  FileSpreadsheet,
  GitCompare,
  RefreshCw,
  Server,
} from "lucide-react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Radar,
} from "recharts";

// Dynamic API base URL: use relative paths so it works both in dev proxy and production
const API_BASE_URL = "/api";

const COLORS = [
  "#3b82f6", "#ef4444", "#f59e0b", "#10b981",
  "#8b5cf6", "#ec4899", "#06b6d4", "#f97316",
];

const METRIC_ICONS = {
  eui: Zap,
  total_kwh: Activity,
  floor_area_sqft: Building2,
  cost_per_sqft: DollarSign,
  peak_cooling_kbtu_h: Thermometer,
  peak_heating_kbtu_h: Thermometer,
  peak_cooling_tons: Wind,
  avg_power_kw: Zap,
  total_annual_cost: DollarSign,
  total_gas_therm: Activity,
  seasonal_variation: BarChart3,
};

const METRIC_UNITS = {
  eui: "kWh/sqft/yr",
  total_kwh: "kWh",
  floor_area_sqft: "sqft",
  cost_per_sqft: "$/sqft/yr",
  peak_cooling_kbtu_h: "kBTU/h",
  peak_heating_kbtu_h: "kBTU/h",
  peak_cooling_tons: "tons",
  avg_power_kw: "kW",
  total_annual_cost: "$",
  total_gas_therm: "therm",
  seasonal_variation: "x",
};

// Toast notification system
function Toast({ toasts, removeToast }) {
  return (
    <div className="fixed top-4 right-4 z-50 space-y-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg border max-w-sm animate-slide-in ${
            toast.type === "success"
              ? "bg-green-50 border-green-200 text-green-800 dark:bg-green-900/30 dark:border-green-800 dark:text-green-300"
              : toast.type === "error"
              ? "bg-red-50 border-red-200 text-red-800 dark:bg-red-900/30 dark:border-red-800 dark:text-red-300"
              : "bg-blue-50 border-blue-200 text-blue-800 dark:bg-blue-900/30 dark:border-blue-800 dark:text-blue-300"
          }`}
        >
          {toast.type === "success" ? (
            <CheckCircle2 size={18} />
          ) : toast.type === "error" ? (
            <AlertCircle size={18} />
          ) : (
            <Info size={18} />
          )}
          <span className="text-sm font-medium flex-1">{toast.message}</span>
          <button onClick={() => removeToast(toast.id)} className="opacity-60 hover:opacity-100">
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

function App() {
  const [darkMode, setDarkMode] = useState(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem("darkMode") === "true";
    }
    return false;
  });
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
  const [loading, setLoading] = useState(false);
  const [vizData, setVizData] = useState(null);
  const [toasts, setToasts] = useState([]);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [healthStatus, setHealthStatus] = useState(null);
  const [comparisonType, setComparisonType] = useState("office");
  const [comparisonData, setComparisonData] = useState(null);

  const chatEndRef = useRef(null);
  const toastIdRef = useRef(0);

  // Dark mode persistence
  useEffect(() => {
    localStorage.setItem("darkMode", darkMode);
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chatHistory, loading]);

  // Health check on mount
  useEffect(() => {
    fetch(`${API_BASE_URL}/health`)
      .then((r) => r.json())
      .then(setHealthStatus)
      .catch(() => setHealthStatus(null));
  }, []);

  const addToast = useCallback((message, type = "info") => {
    const id = ++toastIdRef.current;
    setToasts((prev) => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  const removeToast = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const fileTypes = [
    { key: "ps_e", label: "PS-E Report (All Fuel Meters)", accept: ".txt,.pdf" },
    { key: "ps_e2", label: "PS-E2 Report (Electric Meters)", accept: ".txt,.pdf" },
    { key: "bepu", label: "BEPU Report (Building Performance)", accept: ".txt,.pdf" },
    { key: "ls_c", label: "LS-C Report (Peak Loads)", accept: ".txt,.pdf" },
    { key: "es_d", label: "ES-D Report (Energy Cost)", accept: ".txt,.pdf" },
    { key: "lv_d", label: "LV-D Report (Building Envelope)", accept: ".txt,.pdf" },
    { key: "hourly", label: "Hourly Report", accept: ".csv,.xlsx" },
  ];

  const handleFileChange = (key, event) => {
    const file = event.target.files[0];
    if (file) {
      setFiles((prev) => ({ ...prev, [key]: file }));
    }
  };

  const handleAdditionalDocs = (event) => {
    const fileList = event.target.files;
    if (fileList && fileList.length > 0) {
      setAdditionalDocs(Array.from(fileList));
    }
  };

  const fetchVisualizationData = async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/visualizations`);
      const data = await res.json();
      if (data.success) {
        setVizData(data.visualizations);
      }
    } catch (err) {
      console.error("Failed to fetch viz data:", err);
    }
  };

  const processFiles = async () => {
    if (Object.keys(files).length === 0) {
      addToast("Please select at least one file to process", "error");
      return;
    }

    setProcessing(true);
    setProcessProgress(0);

    const formData = new FormData();
    Object.entries(files).forEach(([key, file]) => {
      if (file) formData.append(key, file);
    });
    additionalDocs.forEach((file) => {
      formData.append("additional_docs", file);
    });
    if (apiKey) formData.append("api_key", apiKey);

    try {
      setProcessProgress(15);
      const response = await fetch(`${API_BASE_URL}/process`, {
        method: "POST",
        body: formData,
      });
      setProcessProgress(60);

      if (!response.ok) throw new Error(`Server error: ${response.status}`);

      const data = await response.json();
      setProcessProgress(90);

      if (data.success) {
        setBuildingData(data.building_data);
        setMetrics(data.metrics);
        setProcessProgress(100);
        addToast(
          `Processed ${data.files_processed} files, ${data.num_chunks} chunks indexed`,
          "success"
        );
        // Fetch visualization data
        await fetchVisualizationData();
      } else {
        throw new Error(data.error || "Processing failed");
      }
    } catch (error) {
      addToast("Processing error: " + error.message, "error");
    } finally {
      setProcessing(false);
      setTimeout(() => setProcessProgress(0), 1000);
    }
  };

  const sendMessage = async () => {
    if (!chatInput.trim()) return;

    const userMessage = chatInput;
    setChatInput("");
    setChatHistory((prev) => [
      ...prev,
      { type: "user", content: userMessage, timestamp: new Date() },
    ]);
    setLoading(true);

    try {
      const response = await fetch(`${API_BASE_URL}/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: userMessage,
          api_key: apiKey,
          include_history: true,
        }),
      });
      const data = await response.json();

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
        throw new Error(data.error || "Query failed");
      }
    } catch (error) {
      setChatHistory((prev) => [
        ...prev,
        { type: "error", content: "Error: " + error.message, timestamp: new Date() },
      ]);
    } finally {
      setLoading(false);
    }
  };

  const clearChat = async () => {
    setChatHistory([]);
    try {
      await fetch(`${API_BASE_URL}/conversation/clear`, { method: "POST" });
    } catch (_) {}
  };

  const searchDocuments = async () => {
    if (!searchQuery.trim()) return;
    setLoading(true);
    try {
      const response = await fetch(`${API_BASE_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: searchQuery }),
      });
      const data = await response.json();
      setSearchResults(data.results || []);
      if ((data.results || []).length === 0) {
        addToast("No results found", "info");
      }
    } catch (error) {
      addToast("Search error: " + error.message, "error");
    } finally {
      setLoading(false);
    }
  };

  const exportData = async (format) => {
    try {
      addToast(`Generating ${format.toUpperCase()} export...`, "info");
      const response = await fetch(`${API_BASE_URL}/export/${format}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.error || `Export failed (${response.status})`);
      }

      if (format === "json") {
        const data = await response.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        downloadBlob(blob, `analysis_${Date.now()}.json`);
      } else if (format === "csv") {
        const blob = await response.blob();
        downloadBlob(blob, `energy_data_${Date.now()}.csv`);
      } else if (format === "pdf") {
        const blob = await response.blob();
        downloadBlob(blob, `report_${Date.now()}.pdf`);
      }
      addToast(`${format.toUpperCase()} exported successfully`, "success");
    } catch (error) {
      addToast("Export error: " + error.message, "error");
    }
  };

  const downloadBlob = (blob, filename) => {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  const runComparison = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ building_type: comparisonType }),
      });
      const data = await response.json();
      if (data.success) {
        setComparisonData(data);
      }
    } catch (error) {
      addToast("Comparison failed: " + error.message, "error");
    }
  };

  // Prepare chart data from vizData
  const getMonthlyChartData = () => {
    if (!vizData?.monthly_consumption) return [];
    const { labels, datasets } = vizData.monthly_consumption;
    return labels.map((month, i) => ({
      month,
      Lights: datasets.Lights?.[i] || 0,
      Equipment: datasets.Equipment?.[i] || 0,
      Heating: datasets.Heating?.[i] || 0,
      Cooling: datasets.Cooling?.[i] || 0,
      Vent_Fans: datasets.Vent_Fans?.[i] || 0,
      Hot_Water: datasets.Hot_Water?.[i] || 0,
      Total: datasets.Total?.[i] || 0,
    }));
  };

  const getEndUsePieData = () => {
    if (!vizData?.end_use_breakdown) return [];
    return Object.entries(vizData.end_use_breakdown)
      .filter(([_, v]) => v > 0)
      .map(([name, value]) => ({
        name: name.replace(/_/g, " "),
        value,
      }));
  };

  const getEuiBenchmarkData = () => {
    if (!vizData?.eui_benchmark) return [];
    const { building, benchmarks } = vizData.eui_benchmark;
    return [
      { name: "Your Building", value: building },
      ...Object.entries(benchmarks).map(([k, v]) => ({
        name: k.replace(/_/g, " "),
        value: v,
      })),
    ];
  };

  const formatMetricValue = (key, value) => {
    if (typeof value !== "number") return value;
    if (key.includes("cost") || key.includes("annual_cost")) {
      return `$${value.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
    }
    if (value > 10000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
    return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  };

  const tabs = [
    { id: "chat", label: "AI Chat", icon: MessageSquare },
    { id: "viz", label: "Visualizations", icon: BarChart3 },
    { id: "metrics", label: "Metrics", icon: Activity },
    { id: "compare", label: "Compare", icon: GitCompare },
    { id: "search", label: "Search", icon: Search },
  ];

  return (
    <div className={`min-h-screen transition-colors duration-300 ${darkMode ? "dark" : ""}`}>
      <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-900 dark:to-slate-800">
        <Toast toasts={toasts} removeToast={removeToast} />

        <div className="flex h-screen">
          {/* Sidebar */}
          <div
            className={`${
              sidebarOpen ? "w-80" : "w-0 overflow-hidden"
            } transition-all duration-300 bg-white dark:bg-slate-900 shadow-xl border-r border-slate-200 dark:border-slate-700 flex flex-col`}
          >
            {/* Header */}
            <div className="p-5 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
              <div>
                <h1 className="text-xl font-bold text-slate-800 dark:text-white flex items-center gap-2">
                  <Brain className="text-blue-600 dark:text-blue-400" size={24} />
                  eQuest AI
                </h1>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                  Energy Modeling Assistant v2.0
                </p>
              </div>
              <button
                onClick={() => setDarkMode(!darkMode)}
                className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700"
              >
                {darkMode ? <Sun size={16} /> : <Moon size={16} />}
              </button>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-4">
              {/* Server Status */}
              {healthStatus && (
                <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800">
                  <Server size={14} className="text-green-600 dark:text-green-400" />
                  <span className="text-xs text-green-700 dark:text-green-300">
                    Server connected
                    {healthStatus.capabilities?.server_api_key && " (API key set)"}
                  </span>
                </div>
              )}

              {/* API Key */}
              <div>
                <label className="block text-xs font-medium text-slate-600 dark:text-slate-400 mb-1.5">
                  OpenAI API Key (Optional)
                </label>
                <input
                  type="password"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder="sk-..."
                  className="w-full px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm bg-white dark:bg-slate-800 text-slate-900 dark:text-white"
                />
              </div>

              {/* File Uploads */}
              <div className="space-y-2">
                <h3 className="font-semibold text-slate-800 dark:text-slate-200 text-xs uppercase tracking-wider">
                  eQuest Files
                </h3>
                {fileTypes.map(({ key, label, accept }) => (
                  <div key={key} className="group">
                    <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
                      {label}
                    </label>
                    <input
                      type="file"
                      accept={accept}
                      onChange={(e) => handleFileChange(key, e)}
                      className="w-full text-xs file:mr-2 file:py-1 file:px-3 file:rounded-md file:border-0 file:bg-blue-50 dark:file:bg-blue-900/30 file:text-blue-700 dark:file:text-blue-300 hover:file:bg-blue-100 dark:hover:file:bg-blue-900/50 file:cursor-pointer file:text-xs text-slate-600 dark:text-slate-400"
                    />
                    {files[key] && (
                      <div className="flex items-center gap-1 mt-1">
                        <CheckCircle2 size={12} className="text-green-500" />
                        <span className="text-xs text-green-600 dark:text-green-400 truncate">
                          {files[key].name}
                        </span>
                      </div>
                    )}
                  </div>
                ))}

                <div className="pt-3">
                  <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">
                    Additional Documents
                  </label>
                  <input
                    type="file"
                    accept=".pdf,.txt"
                    multiple
                    onChange={handleAdditionalDocs}
                    className="w-full text-xs file:mr-2 file:py-1 file:px-3 file:rounded-md file:border-0 file:bg-emerald-50 dark:file:bg-emerald-900/30 file:text-emerald-700 dark:file:text-emerald-300 hover:file:bg-emerald-100 file:cursor-pointer file:text-xs text-slate-600 dark:text-slate-400"
                  />
                  {additionalDocs.length > 0 && (
                    <div className="flex items-center gap-1 mt-1">
                      <CheckCircle2 size={12} className="text-green-500" />
                      <span className="text-xs text-green-600 dark:text-green-400">
                        {additionalDocs.length} file(s) selected
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Process Button */}
              <button
                onClick={processFiles}
                disabled={processing || Object.keys(files).length === 0}
                className="w-full py-2.5 bg-gradient-to-r from-blue-600 to-blue-700 dark:from-blue-500 dark:to-blue-600 text-white rounded-lg font-semibold text-sm hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-lg shadow-blue-500/25"
              >
                {processing ? (
                  <>
                    <Loader2 className="animate-spin" size={16} />
                    Processing... {processProgress}%
                  </>
                ) : (
                  <>
                    <Upload size={16} />
                    Process Files
                  </>
                )}
              </button>
              {processing && (
                <div className="w-full bg-slate-200 dark:bg-slate-700 rounded-full h-1.5">
                  <div
                    className="bg-blue-600 h-1.5 rounded-full transition-all duration-500"
                    style={{ width: `${processProgress}%` }}
                  />
                </div>
              )}

              {/* Status indicator */}
              {buildingData && (
                <div className="p-3 bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg">
                  <div className="flex items-center gap-2">
                    <CheckCircle2 size={14} className="text-green-600 dark:text-green-400" />
                    <span className="text-sm font-medium text-green-800 dark:text-green-300">
                      Data Loaded
                    </span>
                  </div>
                  <p className="text-xs text-green-700 dark:text-green-400 mt-1">
                    {Object.keys(buildingData).length} datasets |{" "}
                    {metrics ? Object.keys(metrics).length : 0} metrics
                  </p>
                </div>
              )}
            </div>

            {/* Export Buttons */}
            {buildingData && (
              <div className="p-3 border-t border-slate-200 dark:border-slate-700 space-y-1.5">
                <div className="grid grid-cols-3 gap-1.5">
                  <button
                    onClick={() => exportData("json")}
                    className="py-2 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg text-xs font-medium flex flex-col items-center gap-1"
                  >
                    <Download size={14} />
                    JSON
                  </button>
                  <button
                    onClick={() => exportData("csv")}
                    className="py-2 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg text-xs font-medium flex flex-col items-center gap-1"
                  >
                    <FileSpreadsheet size={14} />
                    CSV
                  </button>
                  <button
                    onClick={() => exportData("pdf")}
                    className="py-2 bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 rounded-lg text-xs font-medium flex flex-col items-center gap-1"
                  >
                    <FileText size={14} />
                    PDF
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Main Content */}
          <div className="flex-1 flex flex-col min-w-0">
            {/* Top bar with tabs */}
            <div className="bg-white dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700 shadow-sm">
              <div className="flex items-center justify-between px-4 pt-3">
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setSidebarOpen(!sidebarOpen)}
                    className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-500 dark:text-slate-400 lg:hidden"
                  >
                    <ChevronDown
                      size={16}
                      className={`transform transition-transform ${sidebarOpen ? "rotate-90" : "-rotate-90"}`}
                    />
                  </button>
                  <div className="flex gap-1 overflow-x-auto pb-0">
                    {tabs.map(({ id, label, icon: Icon }) => (
                      <button
                        key={id}
                        onClick={() => setActiveTab(id)}
                        className={`px-3 py-2 font-medium text-xs rounded-t-lg flex items-center gap-1.5 whitespace-nowrap transition-colors ${
                          activeTab === id
                            ? "bg-blue-600 dark:bg-blue-500 text-white"
                            : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 hover:bg-slate-200 dark:hover:bg-slate-700"
                        }`}
                      >
                        <Icon size={14} />
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto p-4 md:p-6">
              {/* CHAT TAB */}
              {activeTab === "chat" && (
                <div className="max-w-4xl mx-auto h-full flex flex-col">
                  {!buildingData ? (
                    <div className="flex-1 flex items-center justify-center">
                      <div className="text-center">
                        <Brain size={56} className="text-slate-300 dark:text-slate-600 mx-auto mb-4" />
                        <p className="text-slate-500 dark:text-slate-400 text-sm">
                          Upload and process eQuest files to start chatting
                        </p>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="flex-1 overflow-y-auto space-y-3 mb-4">
                        {chatHistory.length === 0 ? (
                          <div className="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-lg p-5">
                            <h3 className="font-semibold text-blue-900 dark:text-blue-200 mb-3 text-sm">
                              Try asking:
                            </h3>
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                              {[
                                "What is the building's EUI?",
                                "What are the peak cooling loads?",
                                "Show me the energy breakdown by end-use",
                                "Compare heating vs cooling consumption",
                                "What's the most energy-intensive month?",
                                "How does my building compare to benchmarks?",
                              ].map((q) => (
                                <button
                                  key={q}
                                  onClick={() => {
                                    setChatInput(q);
                                  }}
                                  className="text-left text-xs text-blue-700 dark:text-blue-300 bg-blue-100/50 dark:bg-blue-900/30 px-3 py-2 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/50 transition-colors"
                                >
                                  {q}
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : (
                          chatHistory.map((msg, idx) => (
                            <div
                              key={idx}
                              className={`flex gap-2 ${msg.type === "user" ? "justify-end" : ""}`}
                            >
                              {msg.type !== "user" && (
                                <div className="w-7 h-7 rounded-full bg-blue-600 dark:bg-blue-500 flex items-center justify-center flex-shrink-0">
                                  <Brain size={14} className="text-white" />
                                </div>
                              )}
                              <div
                                className={`max-w-[80%] ${
                                  msg.type === "user"
                                    ? "bg-blue-600 dark:bg-blue-500 text-white"
                                    : msg.type === "error"
                                    ? "bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-800 dark:text-red-300"
                                    : "bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-slate-800 dark:text-slate-200"
                                } rounded-lg p-3 shadow-sm`}
                              >
                                <div className="text-sm whitespace-pre-wrap">{msg.content}</div>
                                {msg.sources && msg.sources.length > 0 && (
                                  <div className="mt-2 pt-2 border-t border-slate-200 dark:border-slate-600">
                                    <p className="text-xs text-slate-500 dark:text-slate-400 font-medium mb-1">
                                      Sources:
                                    </p>
                                    <div className="flex flex-wrap gap-1">
                                      {msg.sources.map((source, i) => (
                                        <span
                                          key={i}
                                          className="text-xs bg-slate-100 dark:bg-slate-700 px-2 py-0.5 rounded text-slate-600 dark:text-slate-300"
                                        >
                                          {source}
                                        </span>
                                      ))}
                                    </div>
                                  </div>
                                )}
                              </div>
                            </div>
                          ))
                        )}
                        {loading && (
                          <div className="flex gap-2">
                            <div className="w-7 h-7 rounded-full bg-blue-600 dark:bg-blue-500 flex items-center justify-center">
                              <Loader2 size={14} className="text-white animate-spin" />
                            </div>
                            <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-3 shadow-sm">
                              <div className="flex gap-1">
                                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" />
                                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:150ms]" />
                                <div className="w-2 h-2 bg-slate-400 rounded-full animate-bounce [animation-delay:300ms]" />
                              </div>
                            </div>
                          </div>
                        )}
                        <div ref={chatEndRef} />
                      </div>

                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={chatInput}
                          onChange={(e) => setChatInput(e.target.value)}
                          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
                          placeholder="Ask about your building's energy performance..."
                          className="flex-1 px-4 py-2.5 border border-slate-300 dark:border-slate-600 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm bg-white dark:bg-slate-800 text-slate-900 dark:text-white placeholder:text-slate-400"
                        />
                        <button
                          onClick={sendMessage}
                          disabled={loading || !chatInput.trim()}
                          className="px-4 py-2.5 bg-blue-600 dark:bg-blue-500 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
                        >
                          <Send size={16} />
                        </button>
                        <button
                          onClick={clearChat}
                          className="px-3 py-2.5 bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600"
                        >
                          <Trash2 size={16} />
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* VISUALIZATIONS TAB */}
              {activeTab === "viz" && (
                <div className="max-w-6xl mx-auto space-y-6">
                  {!vizData ? (
                    <div className="text-center py-20">
                      <BarChart3 size={48} className="text-slate-300 dark:text-slate-600 mx-auto mb-3" />
                      <p className="text-slate-500 dark:text-slate-400 text-sm">
                        Process files to view energy visualizations
                      </p>
                    </div>
                  ) : (
                    <>
                      {/* Monthly Consumption Stacked Bar */}
                      {vizData.monthly_consumption && (
                        <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                          <h3 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                            Monthly Energy Consumption by End-Use
                          </h3>
                          <ResponsiveContainer width="100%" height={350}>
                            <BarChart data={getMonthlyChartData()}>
                              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#374151" : "#e5e7eb"} />
                              <XAxis dataKey="month" tick={{ fontSize: 11, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                              <YAxis tick={{ fontSize: 11, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: darkMode ? "#1f2937" : "#fff",
                                  border: `1px solid ${darkMode ? "#374151" : "#e5e7eb"}`,
                                  borderRadius: "8px",
                                  fontSize: "12px",
                                  color: darkMode ? "#e5e7eb" : "#1f2937",
                                }}
                              />
                              <Legend wrapperStyle={{ fontSize: "11px" }} />
                              <Bar dataKey="Cooling" stackId="a" fill="#ef4444" />
                              <Bar dataKey="Heating" stackId="a" fill="#f59e0b" />
                              <Bar dataKey="Lights" stackId="a" fill="#fbbf24" />
                              <Bar dataKey="Equipment" stackId="a" fill="#10b981" />
                              <Bar dataKey="Vent_Fans" stackId="a" fill="#8b5cf6" />
                              <Bar dataKey="Hot_Water" stackId="a" fill="#06b6d4" />
                            </BarChart>
                          </ResponsiveContainer>
                        </div>
                      )}

                      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                        {/* End-Use Pie Chart */}
                        {vizData.end_use_breakdown && (
                          <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                            <h3 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                              Annual End-Use Breakdown
                            </h3>
                            <ResponsiveContainer width="100%" height={300}>
                              <PieChart>
                                <Pie
                                  data={getEndUsePieData()}
                                  cx="50%"
                                  cy="50%"
                                  outerRadius={100}
                                  dataKey="value"
                                  label={({ name, percent }) =>
                                    `${name} (${(percent * 100).toFixed(0)}%)`
                                  }
                                  labelLine={true}
                                >
                                  {getEndUsePieData().map((_, idx) => (
                                    <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
                                  ))}
                                </Pie>
                                <Tooltip
                                  formatter={(val) => val.toLocaleString()}
                                  contentStyle={{
                                    backgroundColor: darkMode ? "#1f2937" : "#fff",
                                    border: `1px solid ${darkMode ? "#374151" : "#e5e7eb"}`,
                                    borderRadius: "8px",
                                    fontSize: "12px",
                                  }}
                                />
                              </PieChart>
                            </ResponsiveContainer>
                          </div>
                        )}

                        {/* EUI Benchmark */}
                        {vizData.eui_benchmark && (
                          <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                            <h3 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                              EUI Benchmark Comparison
                            </h3>
                            <ResponsiveContainer width="100%" height={300}>
                              <BarChart data={getEuiBenchmarkData()} layout="vertical">
                                <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#374151" : "#e5e7eb"} />
                                <XAxis type="number" tick={{ fontSize: 11, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                                <YAxis dataKey="name" type="category" width={100} tick={{ fontSize: 10, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                                <Tooltip
                                  formatter={(val) => `${val} kWh/sqft/yr`}
                                  contentStyle={{
                                    backgroundColor: darkMode ? "#1f2937" : "#fff",
                                    border: `1px solid ${darkMode ? "#374151" : "#e5e7eb"}`,
                                    borderRadius: "8px",
                                    fontSize: "12px",
                                  }}
                                />
                                <Bar dataKey="value" fill="#3b82f6">
                                  {getEuiBenchmarkData().map((entry, idx) => (
                                    <Cell key={idx} fill={idx === 0 ? "#3b82f6" : "#94a3b8"} />
                                  ))}
                                </Bar>
                              </BarChart>
                            </ResponsiveContainer>
                          </div>
                        )}
                      </div>

                      {/* Monthly Trend Line */}
                      {vizData.monthly_consumption && (
                        <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                          <h3 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                            Monthly Total Consumption Trend
                          </h3>
                          <ResponsiveContainer width="100%" height={250}>
                            <LineChart data={getMonthlyChartData()}>
                              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#374151" : "#e5e7eb"} />
                              <XAxis dataKey="month" tick={{ fontSize: 11, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                              <YAxis tick={{ fontSize: 11, fill: darkMode ? "#9ca3af" : "#6b7280" }} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: darkMode ? "#1f2937" : "#fff",
                                  border: `1px solid ${darkMode ? "#374151" : "#e5e7eb"}`,
                                  borderRadius: "8px",
                                  fontSize: "12px",
                                }}
                              />
                              <Line
                                type="monotone"
                                dataKey="Total"
                                stroke="#3b82f6"
                                strokeWidth={2}
                                dot={{ fill: "#3b82f6", r: 4 }}
                                activeDot={{ r: 6 }}
                              />
                            </LineChart>
                          </ResponsiveContainer>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}

              {/* METRICS TAB */}
              {activeTab === "metrics" && (
                <div className="max-w-6xl mx-auto">
                  {!metrics || Object.keys(metrics).length === 0 ? (
                    <div className="text-center py-20">
                      <Activity size={48} className="text-slate-300 dark:text-slate-600 mx-auto mb-3" />
                      <p className="text-slate-500 dark:text-slate-400 text-sm">
                        Process files to view building metrics
                      </p>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
                      {Object.entries(metrics).map(([key, value]) => {
                        const IconComp = METRIC_ICONS[key] || Activity;
                        const unit = METRIC_UNITS[key] || "";
                        return (
                          <div
                            key={key}
                            className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5 hover:shadow-md transition-shadow"
                          >
                            <div className="flex items-center gap-2 mb-3">
                              <div className="p-2 rounded-lg bg-blue-50 dark:bg-blue-900/30">
                                <IconComp size={16} className="text-blue-600 dark:text-blue-400" />
                              </div>
                              <span className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider">
                                {key.replace(/_/g, " ")}
                              </span>
                            </div>
                            <p className="text-2xl font-bold text-slate-800 dark:text-white">
                              {formatMetricValue(key, value)}
                            </p>
                            {unit && (
                              <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
                                {unit}
                              </p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* COMPARE TAB */}
              {activeTab === "compare" && (
                <div className="max-w-4xl mx-auto space-y-6">
                  <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                    <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                      Building Type Comparison
                    </h2>
                    <div className="flex gap-3 mb-4">
                      <select
                        value={comparisonType}
                        onChange={(e) => setComparisonType(e.target.value)}
                        className="flex-1 px-3 py-2 border border-slate-300 dark:border-slate-600 rounded-lg text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white"
                      >
                        <option value="office">Office Building</option>
                        <option value="retail">Retail</option>
                        <option value="hospital">Hospital</option>
                        <option value="school">School</option>
                        <option value="warehouse">Warehouse</option>
                      </select>
                      <button
                        onClick={runComparison}
                        disabled={!buildingData}
                        className="px-4 py-2 bg-blue-600 dark:bg-blue-500 text-white rounded-lg text-sm font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      >
                        <GitCompare size={14} />
                        Compare
                      </button>
                    </div>

                    {!buildingData && (
                      <p className="text-sm text-slate-500 dark:text-slate-400 text-center py-8">
                        Process building data first to run comparisons
                      </p>
                    )}

                    {comparisonData && (
                      <div className="space-y-4">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          {/* EUI Comparison */}
                          {comparisonData.comparison?.eui && (
                            <div
                              className={`p-4 rounded-lg border ${
                                comparisonData.comparison.eui.status === "better"
                                  ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
                                  : comparisonData.comparison.eui.status === "worse"
                                  ? "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
                                  : "bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800"
                              }`}
                            >
                              <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                                Energy Use Intensity (EUI)
                              </p>
                              <p className="text-lg font-bold text-slate-800 dark:text-white">
                                {comparisonData.your_building?.eui?.toFixed(2)} kWh/sqft/yr
                              </p>
                              <p className="text-sm mt-1">
                                <span
                                  className={
                                    comparisonData.comparison.eui.status === "better"
                                      ? "text-green-700 dark:text-green-300"
                                      : comparisonData.comparison.eui.status === "worse"
                                      ? "text-red-700 dark:text-red-300"
                                      : "text-yellow-700 dark:text-yellow-300"
                                  }
                                >
                                  {comparisonData.comparison.eui.difference_pct > 0 ? "+" : ""}
                                  {comparisonData.comparison.eui.difference_pct}% vs{" "}
                                  {comparisonType} benchmark
                                </span>
                              </p>
                            </div>
                          )}

                          {/* Cost Comparison */}
                          {comparisonData.comparison?.cost && (
                            <div
                              className={`p-4 rounded-lg border ${
                                comparisonData.comparison.cost.status === "better"
                                  ? "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800"
                                  : comparisonData.comparison.cost.status === "worse"
                                  ? "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800"
                                  : "bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800"
                              }`}
                            >
                              <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
                                Energy Cost per sqft
                              </p>
                              <p className="text-lg font-bold text-slate-800 dark:text-white">
                                ${comparisonData.your_building?.cost_per_sqft?.toFixed(2)}/sqft/yr
                              </p>
                              <p className="text-sm mt-1">
                                <span
                                  className={
                                    comparisonData.comparison.cost.status === "better"
                                      ? "text-green-700 dark:text-green-300"
                                      : comparisonData.comparison.cost.status === "worse"
                                      ? "text-red-700 dark:text-red-300"
                                      : "text-yellow-700 dark:text-yellow-300"
                                  }
                                >
                                  {comparisonData.comparison.cost.difference_pct > 0 ? "+" : ""}
                                  {comparisonData.comparison.cost.difference_pct}% vs{" "}
                                  {comparisonType} benchmark
                                </span>
                              </p>
                            </div>
                          )}
                        </div>

                        {/* Benchmark reference */}
                        {comparisonData.benchmark && (
                          <div className="bg-slate-50 dark:bg-slate-700/50 rounded-lg p-4">
                            <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2 uppercase tracking-wider">
                              {comparisonType} Benchmarks
                            </p>
                            <div className="grid grid-cols-3 gap-3 text-sm">
                              <div>
                                <p className="text-slate-500 dark:text-slate-400 text-xs">EUI</p>
                                <p className="font-semibold text-slate-800 dark:text-white">
                                  {comparisonData.benchmark.eui} kWh/sqft/yr
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-500 dark:text-slate-400 text-xs">Cost/sqft</p>
                                <p className="font-semibold text-slate-800 dark:text-white">
                                  ${comparisonData.benchmark.cost_sqft}/yr
                                </p>
                              </div>
                              <div>
                                <p className="text-slate-500 dark:text-slate-400 text-xs">
                                  Cooling tons/sqft
                                </p>
                                <p className="font-semibold text-slate-800 dark:text-white">
                                  {comparisonData.benchmark.cooling_tons_per_sqft}
                                </p>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* SEARCH TAB */}
              {activeTab === "search" && (
                <div className="max-w-4xl mx-auto">
                  <div className="bg-white dark:bg-slate-800 rounded-xl shadow-sm border border-slate-200 dark:border-slate-700 p-5">
                    <h2 className="text-sm font-semibold text-slate-800 dark:text-white mb-4">
                      Document Search
                    </h2>
                    <div className="flex gap-2 mb-5">
                      <input
                        type="text"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => e.key === "Enter" && searchDocuments()}
                        placeholder="Search across all documents..."
                        className="flex-1 px-4 py-2 border border-slate-300 dark:border-slate-600 rounded-lg focus:ring-2 focus:ring-blue-500 text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white placeholder:text-slate-400"
                      />
                      <button
                        onClick={searchDocuments}
                        disabled={loading || !searchQuery.trim()}
                        className="px-4 py-2 bg-blue-600 dark:bg-blue-500 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 flex items-center gap-2 text-sm"
                      >
                        {loading ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
                        Search
                      </button>
                    </div>

                    <div className="space-y-3">
                      {searchResults.length === 0 && searchQuery && !loading && (
                        <p className="text-center text-sm text-slate-500 dark:text-slate-400 py-8">
                          No results found. Try a different query.
                        </p>
                      )}
                      {searchResults.map((result, idx) => (
                        <div
                          key={idx}
                          className="border border-slate-200 dark:border-slate-600 rounded-lg p-4 hover:border-blue-300 dark:hover:border-blue-600 transition-colors"
                        >
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <FileText size={14} className="text-slate-400" />
                              <span className="text-xs font-medium text-slate-700 dark:text-slate-300">
                                {result.filename}
                              </span>
                              <span className="text-xs px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                                {result.type}
                              </span>
                            </div>
                            <span className="text-xs text-slate-500 dark:text-slate-400">
                              {(result.score * 100).toFixed(1)}% match
                            </span>
                          </div>
                          <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-3">
                            {result.text}
                          </p>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes slide-in {
          from { transform: translateX(100%); opacity: 0; }
          to { transform: translateX(0); opacity: 1; }
        }
        .animate-slide-in {
          animation: slide-in 0.3s ease-out;
        }
      `}</style>
    </div>
  );
}

export default App;
