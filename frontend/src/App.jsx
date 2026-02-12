import React, { useState, useEffect } from "react";
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
} from "lucide-react";

const API_BASE_URL = "http://localhost:5000/api";

function App() {
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

  const fileTypes = [
    {
      key: "ps_e",
      label: "PS-E Report (All Fuel Meters)",
      accept: ".txt,.pdf",
    },
    {
      key: "ps_e2",
      label: "PS-E2 Report (Electric Meters)",
      accept: ".txt,.pdf",
    },
    {
      key: "bepu",
      label: "BEPU Report (Building Performance)",
      accept: ".txt,.pdf",
    },
    { key: "ls_c", label: "LS-C Report (Peak Loads)", accept: ".txt,.pdf" },
    { key: "es_d", label: "ES-D Report (Energy Cost)", accept: ".txt,.pdf" },
    {
      key: "lv_d",
      label: "LV-D Report (Building Envelope)",
      accept: ".txt,.pdf",
    },
    { key: "hourly", label: "Hourly Report", accept: ".csv,.xlsx" },
  ];

  const handleFileChange = (key, event) => {
    const file = event.target.files[0];
    if (file) {
      setFiles((prev) => ({ ...prev, [key]: file }));
      console.log(`File selected for ${key}:`, file.name);
    }
  };

  const handleAdditionalDocs = (event) => {
    const fileList = event.target.files;
    if (fileList && fileList.length > 0) {
      const filesArray = Array.from(fileList);
      setAdditionalDocs(filesArray);
      console.log(
        `Additional docs selected:`,
        filesArray.map((f) => f.name)
      );
    }
  };

  const processFiles = async () => {
    setProcessing(true);
    setProcessProgress(0);

    const formData = new FormData();

    // Add eQuest files
    Object.entries(files).forEach(([key, file]) => {
      if (file) {
        formData.append(key, file);
        console.log(`Adding ${key}:`, file.name);
      }
    });

    // Add additional documents
    additionalDocs.forEach((file, index) => {
      formData.append("additional_docs", file);
      console.log(`Adding additional doc ${index}:`, file.name);
    });

    // Add API key if provided
    if (apiKey) {
      formData.append("api_key", apiKey);
    }

    // Log what we're sending
    console.log(
      "Total files to upload:",
      Object.keys(files).length + additionalDocs.length
    );

    try {
      setProcessProgress(10);

      const response = await fetch(`${API_BASE_URL}/process`, {
        method: "POST",
        body: formData,
      });

      setProcessProgress(50);

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();

      setProcessProgress(80);

      if (data.success) {
        console.log("Processing successful:", data);
        setBuildingData(data.building_data);
        setMetrics(data.metrics);
        setProcessProgress(100);
        setTimeout(() => {
          setProcessing(false);
          alert("Files processed successfully!");
        }, 500);
      } else {
        throw new Error(data.error || "Processing failed");
      }
    } catch (error) {
      console.error("Processing error:", error);
      alert("Error processing files: " + error.message);
      setProcessing(false);
      setProcessProgress(0);
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
        body: JSON.stringify({ query: userMessage, api_key: apiKey }),
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
      }
    } catch (error) {
      setChatHistory((prev) => [
        ...prev,
        {
          type: "error",
          content: "Error: " + error.message,
          timestamp: new Date(),
        },
      ]);
    } finally {
      setLoading(false);
    }
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
    } catch (error) {
      alert("Search error: " + error.message);
    } finally {
      setLoading(false);
    }
  };

  const exportData = async (format) => {
    try {
      const response = await fetch(`${API_BASE_URL}/export/${format}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ api_key: apiKey }),
      });

      if (format === "json") {
        const data = await response.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `analysis_${Date.now()}.json`;
        a.click();
      } else if (format === "pdf") {
        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `report_${Date.now()}.pdf`;
        a.click();
      }
    } catch (error) {
      alert("Export error: " + error.message);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
      <div className="flex h-screen">
        {/* Sidebar */}
        <div className="w-80 bg-white shadow-xl border-r border-slate-200 flex flex-col">
          <div className="p-6 border-b border-slate-200">
            <h1 className="text-2xl font-bold text-slate-800 flex items-center gap-2">
              <Brain className="text-blue-600" />
              eQuest AI
            </h1>
            <p className="text-sm text-slate-600 mt-1">
              Energy Modeling Assistant
            </p>
          </div>

          <div className="flex-1 overflow-y-auto p-4">
            {/* API Key */}
            <div className="mb-6">
              <label className="block text-sm font-medium text-slate-700 mb-2">
                OpenAI API Key (Optional)
              </label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder="sk-..."
                className="w-full px-3 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
              />
            </div>

            {/* File Uploads */}
            <div className="space-y-3">
              <h3 className="font-semibold text-slate-800 text-sm mb-2">
                eQuest Files
              </h3>
              {fileTypes.map(({ key, label, accept }) => (
                <div key={key}>
                  <label className="block text-xs text-slate-600 mb-1">
                    {label}
                  </label>
                  <input
                    type="file"
                    accept={accept}
                    onChange={(e) => handleFileChange(key, e)}
                    className="w-full text-xs file:mr-2 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 file:cursor-pointer"
                  />
                  {files[key] && (
                    <p className="text-xs text-green-600 mt-1">
                      ✓ {files[key].name}
                    </p>
                  )}
                </div>
              ))}

              <div className="pt-4">
                <label className="block text-xs text-slate-600 mb-1">
                  Additional Documents
                </label>
                <input
                  type="file"
                  accept=".pdf,.txt"
                  multiple
                  onChange={(e) => handleAdditionalDocs(e)}
                  className="w-full text-xs file:mr-2 file:py-1 file:px-3 file:rounded-lg file:border-0 file:bg-green-50 file:text-green-700 hover:file:bg-green-100 file:cursor-pointer"
                />
                {additionalDocs.length > 0 && (
                  <p className="text-xs text-green-600 mt-1">
                    ✓ {additionalDocs.length} file(s) selected
                  </p>
                )}
              </div>
            </div>

            {/* Process Button */}
            <button
              onClick={processFiles}
              disabled={processing || Object.keys(files).length === 0}
              className="w-full mt-6 py-3 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg font-semibold hover:from-blue-700 hover:to-blue-800 disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2 shadow-lg"
            >
              {processing ? (
                <>
                  <Loader2 className="animate-spin" size={18} />
                  Processing... {processProgress}%
                </>
              ) : (
                <>
                  <Upload size={18} />
                  Process Files
                </>
              )}
            </button>

            {buildingData && (
              <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
                <p className="text-sm text-green-800 font-medium">
                  ✓ Files Processed
                </p>
                <p className="text-xs text-green-700 mt-1">
                  {Object.keys(buildingData).length} datasets loaded
                </p>
              </div>
            )}
          </div>

          {/* Export Buttons */}
          {buildingData && (
            <div className="p-4 border-t border-slate-200 space-y-2">
              <button
                onClick={() => exportData("json")}
                className="w-full py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium flex items-center justify-center gap-2"
              >
                <Download size={16} />
                Export JSON
              </button>
              <button
                onClick={() => exportData("pdf")}
                className="w-full py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded-lg text-sm font-medium flex items-center justify-center gap-2"
              >
                <FileText size={16} />
                Generate PDF
              </button>
            </div>
          )}
        </div>

        {/* Main Content */}
        <div className="flex-1 flex flex-col">
          {/* Tabs */}
          <div className="bg-white border-b border-slate-200 shadow-sm">
            <div className="flex gap-1 px-6 pt-4">
              {[
                { id: "chat", label: "AI Chat", icon: MessageSquare },
                { id: "viz", label: "Visualizations", icon: BarChart3 },
                { id: "metrics", label: "Metrics", icon: BarChart3 },
                { id: "search", label: "Search", icon: Search },
              ].map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setActiveTab(id)}
                  className={`px-4 py-2 font-medium text-sm rounded-t-lg flex items-center gap-2 transition-colors ${
                    activeTab === id
                      ? "bg-blue-600 text-white"
                      : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                  }`}
                >
                  <Icon size={16} />
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Tab Content */}
          <div className="flex-1 overflow-y-auto p-6">
            {activeTab === "chat" && (
              <div className="max-w-4xl mx-auto h-full flex flex-col">
                {!buildingData ? (
                  <div className="flex-1 flex items-center justify-center">
                    <div className="text-center">
                      <Brain
                        size={64}
                        className="text-slate-300 mx-auto mb-4"
                      />
                      <p className="text-slate-600">
                        Upload and process files to start chatting
                      </p>
                    </div>
                  </div>
                ) : (
                  <>
                    <div className="flex-1 overflow-y-auto space-y-4 mb-4">
                      {chatHistory.length === 0 ? (
                        <div className="bg-blue-50 border border-blue-200 rounded-lg p-6">
                          <h3 className="font-semibold text-blue-900 mb-3">
                            Example Questions:
                          </h3>
                          <ul className="space-y-2 text-sm text-blue-800">
                            <li>• What is the building's EUI?</li>
                            <li>• What are the peak cooling loads?</li>
                            <li>• Show me the energy breakdown by end-use</li>
                            <li>• Compare heating vs cooling consumption</li>
                            <li>• What's the most energy-intensive month?</li>
                          </ul>
                        </div>
                      ) : (
                        chatHistory.map((msg, idx) => (
                          <div
                            key={idx}
                            className={`flex gap-3 ${
                              msg.type === "user" ? "justify-end" : ""
                            }`}
                          >
                            {msg.type !== "user" && (
                              <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center flex-shrink-0">
                                <Brain size={18} className="text-white" />
                              </div>
                            )}
                            <div
                              className={`max-w-3xl ${
                                msg.type === "user"
                                  ? "bg-blue-600 text-white"
                                  : "bg-white border border-slate-200"
                              } rounded-lg p-4 shadow-sm`}
                            >
                              <div
                                className={`prose prose-sm ${
                                  msg.type === "user" ? "prose-invert" : ""
                                }`}
                              >
                                {msg.content.split("\n").map((line, i) => (
                                  <p key={i} className="mb-2 last:mb-0">
                                    {line}
                                  </p>
                                ))}
                              </div>
                              {msg.sources && msg.sources.length > 0 && (
                                <div className="mt-3 pt-3 border-t border-slate-200">
                                  <p className="text-xs text-slate-600 font-medium mb-1">
                                    Sources:
                                  </p>
                                  <div className="flex flex-wrap gap-1">
                                    {msg.sources.map((source, i) => (
                                      <span
                                        key={i}
                                        className="text-xs bg-slate-100 px-2 py-1 rounded"
                                      >
                                        {source}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                            {msg.type === "user" && (
                              <div className="w-8 h-8 rounded-full bg-slate-300 flex items-center justify-center flex-shrink-0">
                                👤
                              </div>
                            )}
                          </div>
                        ))
                      )}
                      {loading && (
                        <div className="flex gap-3">
                          <div className="w-8 h-8 rounded-full bg-blue-600 flex items-center justify-center">
                            <Loader2
                              size={18}
                              className="text-white animate-spin"
                            />
                          </div>
                          <div className="bg-white border border-slate-200 rounded-lg p-4 shadow-sm">
                            <p className="text-slate-600">Thinking...</p>
                          </div>
                        </div>
                      )}
                    </div>

                    <div className="flex gap-2">
                      <input
                        type="text"
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyPress={(e) => e.key === "Enter" && sendMessage()}
                        placeholder="Ask a question about your building's energy performance..."
                        className="flex-1 px-4 py-3 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                      />
                      <button
                        onClick={sendMessage}
                        disabled={loading || !chatInput.trim()}
                        className="px-6 py-3 bg-blue-600 text-white rounded-lg font-medium hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                      >
                        <Send size={18} />
                      </button>
                      <button
                        onClick={() => setChatHistory([])}
                        className="px-4 py-3 bg-slate-200 text-slate-700 rounded-lg hover:bg-slate-300"
                      >
                        <Trash2 size={18} />
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}

            {activeTab === "viz" && (
              <div className="max-w-6xl mx-auto">
                {!buildingData ? (
                  <p className="text-center text-slate-600">
                    Process files to view visualizations
                  </p>
                ) : (
                  <div className="bg-white rounded-lg shadow-lg p-6">
                    <h2 className="text-xl font-bold text-slate-800 mb-4">
                      Energy Visualizations
                    </h2>
                    <p className="text-slate-600">
                      Charts will be rendered here using Chart.js or Plotly
                    </p>
                  </div>
                )}
              </div>
            )}

            {activeTab === "metrics" && (
              <div className="max-w-6xl mx-auto">
                {!metrics ? (
                  <p className="text-center text-slate-600">
                    Process files to view metrics
                  </p>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    {Object.entries(metrics).map(([key, value]) => (
                      <div
                        key={key}
                        className="bg-white rounded-lg shadow-lg p-6"
                      >
                        <p className="text-sm text-slate-600 mb-1">
                          {key.replace(/_/g, " ").toUpperCase()}
                        </p>
                        <p className="text-3xl font-bold text-slate-800">
                          {typeof value === "number" ? value.toFixed(2) : value}
                        </p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {activeTab === "search" && (
              <div className="max-w-4xl mx-auto">
                <div className="bg-white rounded-lg shadow-lg p-6">
                  <h2 className="text-xl font-bold text-slate-800 mb-4">
                    Document Search
                  </h2>
                  <div className="flex gap-2 mb-6">
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyPress={(e) => e.key === "Enter" && searchDocuments()}
                      placeholder="Search across all documents..."
                      className="flex-1 px-4 py-2 border border-slate-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    />
                    <button
                      onClick={searchDocuments}
                      disabled={loading}
                      className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                    >
                      <Search size={18} />
                    </button>
                  </div>

                  <div className="space-y-4">
                    {searchResults.map((result, idx) => (
                      <div
                        key={idx}
                        className="border border-slate-200 rounded-lg p-4"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-sm font-medium text-slate-700">
                            {result.filename}
                          </span>
                          <span className="text-xs text-slate-500">
                            Relevance: {(result.score * 100).toFixed(1)}%
                          </span>
                        </div>
                        <p className="text-sm text-slate-600">{result.text}</p>
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
  );
}

export default App;
