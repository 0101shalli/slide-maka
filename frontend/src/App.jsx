import React, { useMemo, useState, useEffect, useRef } from "react";
import { PreviewCard } from "./components/PreviewCard";

const palettes = [
  { id: 1, name: "Ocean", primary: "#0B3C5D", secondary: "#1D5C7C", accent: "#3A7CA5", background: "#F0F8FF" },
  { id: 2, name: "Forest", primary: "#2F5233", secondary: "#4A7C59", accent: "#6B9F7F", background: "#F0FFF0" },
  { id: 3, name: "Sunset", primary: "#C44536", secondary: "#D2691E", accent: "#FF6347", background: "#FFF8DC" },
];

const defaultTemplateBlocks = [
  { id: "cover", type: "cover", title: "Presentation Title", subtitle: "Subtitle here", backgroundColor: "#0B523E", textColor: "#FFFFFF", layout: "center", design: "modern", elements: [] },
  { id: "outline", type: "outline", title: "Outline of Presentation", subtitle: "Key sections and flow", backgroundColor: "#F0F7F2", textColor: "#0B523E", layout: "default", design: "minimal", elements: [] },
  { id: "theory", type: "content", flavor: "theory", title: "Theoretical Background", subtitle: "Concepts, definitions and principles", backgroundColor: "#F0F7F2", textColor: "#0B523E", layout: "bullets", design: "modern", elements: [] },
  { id: "practical", type: "content", flavor: "practical", title: "Practical Application", subtitle: "How it works in practice", backgroundColor: "#F0F7F2", textColor: "#0B523E", layout: "default", design: "minimal", elements: [] },
  { id: "overview", type: "image", title: "Visual Overview", subtitle: "Diagram of the key concepts", backgroundColor: "#FFFFFF", textColor: "#0B523E", layout: "fullscreen", design: "minimal", elements: [] },
  { id: "end", type: "end", title: "Thank You", subtitle: "Questions & discussion", backgroundColor: "#0B523E", textColor: "#FFFFFF", design: "modern", elements: [] },
];

function contrastText(hex) {
  const h = String(hex || "").replace("#", "");
  if (!/^[0-9a-fA-F]{6}$/.test(h)) return "#1A1A1A";
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return 0.299 * r + 0.587 * g + 0.114 * b < 140 ? "#FFFFFF" : "#1A1A1A";
}

function round2(v) {
  return Math.round(v * 100) / 100;
}

function pencilPath(points) {
  const pts = (points || []).filter((p) => Array.isArray(p) && p.length >= 2).map((p) => [round2(Number(p[0])), round2(Number(p[1]))]);
  if (pts.length < 2) return "";
  if (pts.length === 2) return `M ${pts[0][0]} ${pts[0][1]} L ${pts[1][0]} ${pts[1][1]}`;
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 1; i < pts.length - 1; i++) {
    const p1 = pts[i];
    const ex = (p1[0] + pts[i + 1][0]) / 2;
    const ey = (p1[1] + pts[i + 1][1]) / 2;
    d += ` Q ${p1[0]} ${p1[1]} ${round2(ex)} ${round2(ey)}`;
  }
  const last = pts[pts.length - 1];
  d += ` L ${last[0]} ${last[1]}`;
  return d;
}

function polygonPts(cx, cy, radius, count, startAngleDeg, innerRatio = 1) {
  const pts = [];
  for (let i = 0; i < count; i++) {
    const r = i % 2 === 0 ? radius : radius * innerRatio;
    const a = ((startAngleDeg + i * (360 / count)) * Math.PI) / 180;
    pts.push([cx + r * Math.sin(a), cy - r * Math.cos(a)]);
  }
  return pts;
}

function ptsToPath(pts) {
  if (!pts.length) return "";
  return `M ${round2(pts[0][0])} ${round2(pts[0][1])}` + pts.slice(1).map((p) => ` L ${round2(p[0])} ${round2(p[1])}`).join("") + " Z";
}

function shapeSVGPath(type) {
  switch (type) {
    case "rect":
    case "square":
      return "M 0 0 H 100 V 100 H 0 Z";
    case "ellipse":
    case "circle":
      return "M 50 0 A 50 50 0 0 1 50 100 A 50 50 0 0 1 50 0 Z";
    case "triangle":
      return ptsToPath([[50, 0], [0, 100], [100, 100]]);
    case "right_triangle":
      return ptsToPath([[0, 0], [100, 100], [0, 100]]);
    case "pentagon":
      return ptsToPath(polygonPts(50, 50, 47, 5, -90));
    case "hexagon":
      return ptsToPath(polygonPts(50, 50, 48, 6, 30));
    case "arrowRight":
      return ptsToPath([[0, 35], [60, 35], [60, 8], [100, 50], [60, 92], [60, 65], [0, 65]]);
    case "arrowLeft":
      return ptsToPath([[100, 35], [40, 35], [40, 8], [0, 50], [40, 92], [40, 65], [100, 65]]);
    case "star4":
      return ptsToPath(polygonPts(50, 50, 48, 8, -90, 0.26));
    case "star5":
      return ptsToPath(polygonPts(50, 50, 48, 10, -90, 0.382));
    case "star6":
      return ptsToPath(polygonPts(50, 50, 48, 12, -90, 0.5));
    case "heart":
      return "M 50 92 C 26 68 6 54 6 34 C 6 22 16 10 26 12 C 33 13 40 22 50 22 C 60 22 67 13 74 12 C 84 10 94 22 94 34 C 94 54 74 68 50 92 Z";
    case "calloutRect":
      return "M 14 0 H 86 Q 100 0 100 14 V 86 Q 100 100 86 100 H 14 Q 0 100 0 86 V 14 Q 0 0 14 0 Z";
    case "calloutOval":
      return "M 50 0 A 50 32 0 0 1 50 64 A 50 32 0 0 1 50 0 Z";
    case "calloutCloud":
      return "M 35 14 C 52 4 74 8 80 20 C 96 22 99 42 88 52 C 98 64 80 82 66 82 C 45 92 14 84 14 68 C 0 62 4 34 18 30 C 18 20 24 14 35 14 Z";
    default:
      return "M 0 0 H 100 V 100 H 0 Z";
  }
}

export function App() {
  const [slideCount, setSlideCount] = useState(10);
  const [theoryPercent, setTheoryPercent] = useState(70);
  const [imagePercent, setImagePercent] = useState(30);
  const [audienceLevel, setAudienceLevel] = useState("Beginner");
  const [paletteId, setPaletteId] = useState(1);
  const [contentType, setContentType] = useState("text");
  const [text, setText] = useState("");
  const [contentFile, setContentFile] = useState(null);
  const [promptText, setPromptText] = useState("");
  const [title, setTitle] = useState("");
  const [logoUrl, setLogoUrl] = useState("");
  const [logoFile, setLogoFile] = useState(null);
  const [templateId, setTemplateId] = useState(0);
  const [templates, setTemplates] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [templateDescription, setTemplateDescription] = useState("");
  const [templateJson, setTemplateJson] = useState("");
  const [templateFileUpload, setTemplateFileUpload] = useState(null);
  const [templateBlocks, setTemplateBlocks] = useState(defaultTemplateBlocks);
  const [dragIndex, setDragIndex] = useState(null);
  const [templateStatus, setTemplateStatus] = useState("");
  const [templateError, setTemplateError] = useState(null);
  const [status, setStatus] = useState("Idle");
  const [error, setError] = useState(null);
  const [previewSlides, setPreviewSlides] = useState([]);
  const [downloadLinks, setDownloadLinks] = useState({ pptx: null, pdf: null });
  const [presentationId, setPresentationId] = useState(null);
  const [currentPage, setCurrentPage] = useState("home");
  const [userSlides, setUserSlides] = useState([]);
  const [userSlidesLoading, setUserSlidesLoading] = useState(false);
  const [userSlidesError, setUserSlidesError] = useState(null);
  const [templatesError, setTemplatesError] = useState(null);
  const isAdmin = true; // Set this to false for non-admin users
  const apiBase = "http://localhost:8001";

  const theme = "light";
  const [themeDark, setThemeDark] = useState(false);
  const [templateTab, setTemplateTab] = useState("builder");
  const [showTemplatesModal, setShowTemplatesModal] = useState(false);
  const [templatesModalError, setTemplatesModalError] = useState(null);
  const [dragTool, setDragTool] = useState(null);

  const currentUserId = 1;
  const [currentUser, setCurrentUser] = useState({
    id: 1, username: "Administrator", email: "admin@slidemaka.com", role: "admin", is_active: true,
  });
  const hasAdminRights = currentUser.role === "admin" || currentUser.is_admin || currentUserId === 1;

  const [users, setUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [usersError, setUsersError] = useState(null);
  const [showUserModal, setShowUserModal] = useState(false);
  const [userModalMode, setUserModalMode] = useState("create");
  const [userForm, setUserForm] = useState({ id: null, username: "", email: "", password: "", role: "user", is_active: true });
  const [profileStatus, setProfileStatus] = useState("");
  const [profileError, setProfileError] = useState(null);
  const [llmProviders, setLlmProviders] = useState([]);
  const [llmLoading, setLlmLoading] = useState(false);
  const [llmError, setLlmError] = useState(null);
  const [showProviderModal, setShowProviderModal] = useState(false);
  const [providerModalMode, setProviderModalMode] = useState("create");
  const [providerForm, setProviderForm] = useState({
    id: null, name: "", provider_type: "openai", base_url: "", model: "",
    api_key: "", priority: 100, enabled: true, is_default: false, extra_json: "{}",
  });
  const [providerStatus, setProviderStatus] = useState("");
  const [providerTestResult, setProviderTestResult] = useState(null);

  const ribbonTools = [
    { type: "cover", flavor: null, label: "🎬 Cover Slide" },
    { type: "outline", flavor: null, label: "📜 Outline Slide" },
    { type: "content", flavor: "theory", label: "📘 Theory Content" },
    { type: "content", flavor: "practical", label: "🛠️ Practical Content" },
    { type: "image", flavor: null, label: "🖼️ Image / Diagram Slide" },
    { type: "end", flavor: null, label: "🏁 End Slide" },
  ];

  const basicTools = [
    { id: "text", label: "📝 Text Area" },
    { id: "line", label: "➖ Line" },
    { id: "image", label: "🖼️ Image Placeholder" },
    { id: "pencil", label: "✏️ Pencil (freehand)" },
  ];

  const shapeTools = [
    { id: "rect", label: "⬜ Rectangle" },
    { id: "square", label: "▦ Square" },
    { id: "circle", label: "⚪ Circle" },
    { id: "ellipse", label: "⬮ Ellipse" },
    { id: "triangle", label: "△ Triangle" },
    { id: "right_triangle", label: "◺ Right Triangle" },
    { id: "pentagon", label: "⬠ Pentagon" },
    { id: "hexagon", label: "⬡ Hexagon" },
    { id: "arrowRight", label: "➔ Arrow Right" },
    { id: "arrowLeft", label: "⬅ Arrow Left" },
    { id: "star4", label: "✴ Star 4" },
    { id: "star5", label: "⭐ Star 5" },
    { id: "star6", label: "✶ Star 6" },
    { id: "heart", label: "❤ Heart" },
    { id: "calloutRect", label: "💬 Rounded Rect Callout" },
    { id: "calloutOval", label: "🫧 Rounded Oval Callout" },
    { id: "calloutCloud", label: "☁️ Cloud Callout" },
  ];

  const canvasTools = [...basicTools, ...shapeTools];

  function shapeDefault(tool, w, h) {
    return { type: tool, x: 8, y: 8, w, h, fill: "#147A45", outline_color: "#0B523E", outline_width: 2, rotation: 0 };
  }

  const ELEMENT_DEFAULTS = {
    text: { type: "text", x: 8, y: 8, w: 42, h: 14, text: "Text area", font_size: 18, fill: "#FFFFFF", outline_color: "", outline_width: 0, rotation: 0 },
    rect: shapeDefault("rect", 30, 22),
    square: shapeDefault("square", 18, 18),
    ellipse: shapeDefault("ellipse", 20, 20),
    circle: shapeDefault("circle", 18, 18),
    triangle: shapeDefault("triangle", 24, 20),
    right_triangle: shapeDefault("right_triangle", 24, 20),
    pentagon: shapeDefault("pentagon", 20, 20),
    hexagon: shapeDefault("hexagon", 22, 20),
    arrowLeft: shapeDefault("arrowLeft", 30, 18),
    arrowRight: shapeDefault("arrowRight", 30, 18),
    star4: shapeDefault("star4", 22, 22),
    star5: shapeDefault("star5", 22, 22),
    star6: shapeDefault("star6", 22, 22),
    heart: shapeDefault("heart", 24, 22),
    calloutRect: shapeDefault("calloutRect", 30, 18),
    calloutOval: shapeDefault("calloutOval", 30, 18),
    calloutCloud: shapeDefault("calloutCloud", 30, 20),
    line: { type: "line", x: 10, y: 45, w: 60, h: 1.5, fill: "#D4A01E", stroke_color: "#D4A01E", stroke_width: 4, outline_color: "", outline_width: 0, rotation: 0 },
    image: { type: "image", x: 5, y: 20, w: 35, h: 35, fill: "#B9C4CE", outline_color: "#0B523E", outline_width: 2, rotation: 0 },
    pencil: { type: "pencil", x: 10, y: 10, w: 30, h: 30, points: [], stroke_color: "#0B523E", stroke_width: 3, fill: "transparent" },
  };

  const RESIZE_HANDLES = ["nw", "n", "ne", "e", "se", "s", "sw", "w"];

  const [dragToolItem, setDragToolItem] = useState(null);
  const [selectedBlock, setSelectedBlock] = useState(null);
  const [selectedElement, setSelectedElement] = useState(null);
  const [armedPencil, setArmedPencil] = useState(false);
  const [pencilTool, setPencilTool] = useState({ stroke_width: 3, stroke_color: "#0B523E" });
  const [drawPreview, setDrawPreview] = useState(null);
  const dragState = useRef(null);
  const drawingRef = useRef(null);

  function slotKeyOf(type, flavor) {
    if (type === "content") return `content_${flavor || "?"}`;
    return type;
  }

  function buildTemplateSlots() {
    const slots = new Set();
    for (const b of templateBlocks) {
      if (b.type === "content" && !b.flavor) {
        slots.add("content_unset");
        continue;
      }
      slots.add(slotKeyOf(b.type, b.flavor));
    }
    return slots;
  }

  function addBlockElement(blockIndex, tool, xPct = null, yPct = null) {
    const d = ELEMENT_DEFAULTS[tool];
    if (!d) return;
    const base = { ...d, id: `${tool}-${Date.now()}-${Math.random().toString(36).slice(2, 6)}` };
    if (tool === "pencil" && !(base.points && base.points.length)) {
      base.points = [[5, 90], [30, 20], [60, 85], [95, 25]];
    }
    if (xPct !== null && yPct !== null) {
      base.x = Math.max(0, Math.min(100, xPct));
      base.y = Math.max(0, Math.min(100, yPct));
    }
    setTemplateBlocks((current) => current.map((block, idx) =>
      idx === blockIndex ? { ...block, elements: [...(block.elements || []), base] } : block
    ));
    setSelectedBlock(blockIndex);
    setSelectedElement(base.id);
  }

  function dropElementOnBlock(blockIndex, event) {
    const rect = event.currentTarget.getBoundingClientRect();
    const xPct = ((event.clientX - rect.left) / rect.width) * 100;
    const yPct = ((event.clientY - rect.top) / rect.height) * 100;
    addBlockElement(blockIndex, dragToolItem, xPct, yPct);
    setDragToolItem(null);
  }

  function updateBlockElement(blockIndex, elementId, patch) {
    setTemplateBlocks((current) => current.map((block, idx) => {
      if (idx !== blockIndex) return block;
      return { ...block, elements: (block.elements || []).map((el) => el.id === elementId ? { ...el, ...patch } : el) };
    }));
  }

  function removeBlockElement(blockIndex, elementId) {
    setTemplateBlocks((current) => current.map((block, idx) =>
      idx === blockIndex ? { ...block, elements: (block.elements || []).filter((el) => el.id !== elementId) } : block
    ));
    if (selectedBlock === blockIndex && selectedElement === elementId) setSelectedElement(null);
  }

  function elementPointerDown(event, blockIndex, elementId) {
    event.preventDefault();
    event.stopPropagation();
    setSelectedBlock(blockIndex);
    setSelectedElement(elementId);
    const canvas = event.currentTarget.closest(".slide-canvas");
    const rect = canvas.getBoundingClientRect();
    const block = templateBlocks[blockIndex];
    const el = (block.elements || []).find((e) => e.id === elementId);
    if (!el) return;
    dragState.current = {
      blockIndex,
      elementId,
      mode: "move",
      offX: ((event.clientX - rect.left) / rect.width) * 100 - el.x,
      offY: ((event.clientY - rect.top) / rect.height) * 100 - el.y,
      startClientX: event.clientX,
      startClientY: event.clientY,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function elementResizeStart(event, blockIndex, elementId, handle = "se") {
    event.preventDefault();
    event.stopPropagation();
    dragState.current = { blockIndex, elementId, mode: "resize", handle, startX: event.clientX, startY: event.clientY, id: elementId };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function elementRotateStart(event, blockIndex, elementId) {
    event.preventDefault();
    event.stopPropagation();
    const canvas = event.currentTarget.closest(".slide-canvas");
    const rect = canvas.getBoundingClientRect();
    const block = templateBlocks[blockIndex];
    const el = (block.elements || []).find((e) => e.id === elementId);
    if (!el) return;
    const cx = ((el.x + el.w / 2) / 100) * rect.width;
    const cy = ((el.y + el.h / 2) / 100) * rect.height;
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const angle = Math.atan2(px - cx, py - cy) * (180 / Math.PI);
    const base = ((Number(el.rotation) || 0) % 360 + 360) % 360;
    dragState.current = { blockIndex, elementId, mode: "rotate", cx, cy, offset: angle - base };
    event.currentTarget.setPointerCapture(event.pointerId);
  }

  function elementPointerMove(event, blockIndex, elementId) {
    const d = dragState.current;
    if (!d || d.elementId !== elementId || d.blockIndex !== blockIndex) return;
    const canvas = event.currentTarget.closest(".slide-canvas");
    const rect = canvas.getBoundingClientRect();
    const block = templateBlocks[blockIndex];
    const el = (block.elements || []).find((e) => e.id === elementId);
    if (!el) return;
    if (d.mode === "move") {
      const x = ((event.clientX - rect.left) / rect.width) * 100 - d.offX;
      const y = ((event.clientY - rect.top) / rect.height) * 100 - d.offY;
      updateBlockElement(blockIndex, elementId, {
        x: Math.max(0, Math.min(100 - el.w, x)),
        y: Math.max(0, Math.min(100 - el.h, y)),
      });
    } else if (d.mode === "rotate") {
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      const angle = Math.atan2(px - d.cx, py - d.cy) * (180 / Math.PI);
      const rot = ((angle - d.offset) % 360 + 360) % 360;
      updateBlockElement(blockIndex, elementId, { rotation: Math.round(rot) });
    } else if (d.mode === "resize") {
      const MIN = 2;
      const px = Math.max(0, Math.min(100, ((event.clientX - rect.left) / rect.width) * 100));
      const py = Math.max(0, Math.min(100, ((event.clientY - rect.top) / rect.height) * 100));
      let x0 = el.x, y0 = el.y, x1 = el.x + el.w, y1 = el.y + el.h;
      const hnd = d.handle || "se";
      if (hnd.includes("e")) x1 = px;
      if (hnd.includes("s")) y1 = py;
      if (hnd.includes("w")) x0 = px;
      if (hnd.includes("n")) y0 = py;
      if (x1 - x0 < MIN) { x1 = x0 + MIN; }
      if (y1 - y0 < MIN) { y1 = y0 + MIN; }
      const nx = Math.max(0, Math.min(x0, 100 - MIN));
      const ny = Math.max(0, Math.min(y0, 100 - MIN));
      const nx2 = Math.max(x0, x1);
      const ny2 = Math.max(y0, y1);
      updateBlockElement(blockIndex, elementId, {
        x: nx,
        y: ny,
        w: Math.max(MIN, Math.min(100 - nx, nx2 - nx)),
        h: Math.max(MIN, Math.min(100 - ny, ny2 - ny)),
      });
    }
  }

  function elementPointerUp(event) {
    if (event && event.currentTarget && dragState.current) {
      try { event.currentTarget.releasePointerCapture(event.pointerId); } catch (e) { /* noop */ }
    }
    dragState.current = null;
  }

  function canvasDrawStart(event, blockIndex) {
    if (!armedPencil) return;
    event.preventDefault();
    event.stopPropagation();
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(100, round2(((event.clientX - rect.left) / rect.width) * 100)));
    const y = Math.max(0, Math.min(100, round2(((event.clientY - rect.top) / rect.height) * 100)));
    drawingRef.current = { blockIndex, points: [[x, y]] };
    try { event.currentTarget.setPointerCapture(event.pointerId); } catch (e) { /* noop */ }
  }

  function canvasDrawMove(event) {
    const d = drawingRef.current;
    if (!d) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const x = Math.max(0, Math.min(100, round2(((event.clientX - rect.left) / rect.width) * 100)));
    const y = Math.max(0, Math.min(100, round2(((event.clientY - rect.top) / rect.height) * 100)));
    d.points.push([x, y]);
    setDrawPreview({ block: d.blockIndex, points: [...d.points], stroke_width: pencilTool.stroke_width, stroke_color: pencilTool.stroke_color });
  }

  function canvasDrawEnd(event) {
    const d = drawingRef.current;
    if (!d) return;
    drawingRef.current = null;
    try { if (event && event.currentTarget) event.currentTarget.releasePointerCapture(event.pointerId); } catch (e) { /* noop */ }
    const pts = d.points;
    setDrawPreview(null);
    if (!pts || pts.length < 2) {
      setArmedPencil(false);
      return;
    }
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const minX = Math.min(...xs);
    const minY = Math.min(...ys);
const w = Math.max(Math.max(...xs) - minX, 2);
      const h = Math.max(Math.max(...ys) - minY, 2);
      const element = {
        id: `pencil-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        type: "pencil",
        x: +round2(minX),
        y: +round2(minY),
        w: +round2(w),
        h: +round2(h),
        points: pts.map(([px, py]) => [+round2(((px - minX) / w) * 100), +round2(((py - minY) / h) * 100)]),
        stroke_color: pencilTool.stroke_color,
        stroke_width: pencilTool.stroke_width,
      };
    setTemplateBlocks((current) => current.map((block, idx) =>
      idx === d.blockIndex ? { ...block, elements: [...(block.elements || []), element] } : block
    ));
    setSelectedBlock(d.blockIndex);
    setSelectedElement(element.id);
    setArmedPencil(false);
  }

  useEffect(() => {
    function handleKeyDown(event) {
      const target = event.target;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT")) return;
      if ((event.key === "Delete" || event.key === "Backspace") && selectedBlock !== null && selectedElement) {
        event.preventDefault();
        removeBlockElement(selectedBlock, selectedElement);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedBlock, selectedElement, templateBlocks]);

  async function loadTemplates() {
    try {
      setTemplatesError(null);
      const response = await fetch(`${apiBase}/api/templates`);
      if (!response.ok) {
        throw new Error(`Failed to load templates (${response.status})`);
      }
      const data = await response.json();
      setTemplates(data);
      // Keep the current pick when it still exists, otherwise fall back to the
      // first saved template. Reading templateId from a closure here left a
      // deleted template selected, so the deck was generated with a template
      // the user could no longer see in the dropdown.
      setTemplateId((current) => {
        if (data.length === 0) return 0;
        const stillThere = data.some((template) => Number(template.id) === Number(current));
        return stillThere ? Number(current) : Number(data[0].id);
      });
    } catch (err) {
      setTemplatesError(err instanceof Error ? err.message : "Unable to load templates");
    }
  }

  useEffect(() => {
    loadTemplates();
  }, [apiBase]);

  const wordCount = useMemo(() => text.trim().split(/\s+/).filter(Boolean).length, [text]);
  const practicalPercent = 100 - theoryPercent;

  // Function to clean text: remove excess spaces and special characters except @
  function cleanText(inputText) {
    // Remove all special characters except @ and spaces
    let cleaned = inputText.replace(/[^a-zA-Z0-9\s@]/g, '');
    // Replace multiple spaces with single space
    cleaned = cleaned.replace(/\s+/g, ' ');
    // Trim leading and trailing spaces
    return cleaned.trim();
  }

  // Preserve the pasted text structure: keep line breaks and bullet markers,
  // only normalizing line endings and dropping stray control characters.
  function preserveTextStructure(inputText) {
    return (inputText || '')
      .replace(/\r\n?/g, '\n')
      .replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, '')
      .trim();
  }

  async function loadUserSlides() {
    try {
      setUserSlidesLoading(true);
      setUserSlidesError(null);
      console.log('Loading user slides...');
      const response = await fetch(`${apiBase}/api/presentations/user/1`);
      console.log('Response status:', response.status);
      if (response.ok) {
        const slides = await response.json();
        console.log('Loaded slides:', slides);
        setUserSlides(slides);
      } else {
        const errorMsg = `Failed to load slides (${response.status})`;
        console.error(errorMsg);
        setUserSlidesError(errorMsg);
      }
    } catch (err) {
      const errorMsg = `Network error: ${err.message}`;
      console.error("Failed to load user slides:", err);
      setUserSlidesError(errorMsg);
    } finally {
      setUserSlidesLoading(false);
    }
  }

  async function deleteSlide(slideId) {
    if (!confirm("Are you sure you want to delete this presentation?")) {
      return;
    }

    try {
      console.log(`Attempting to delete presentation ${slideId}...`);
      const response = await fetch(`${apiBase}/api/presentations/${slideId}`, {
        method: "DELETE",
      });

      console.log('Delete response status:', response.status);
      if (response.ok) {
        console.log('Presentation deleted successfully, reloading slides...');
        // Reload the slides list
        await loadUserSlides();
        alert("Presentation deleted successfully!");
      } else {
        const errorData = await response.json().catch(() => ({}));
        const errorMsg = errorData.detail || `Failed to delete presentation (${response.status})`;
        console.error('Delete failed:', errorMsg);
        alert(`Failed to delete: ${errorMsg}`);
      }
    } catch (err) {
      console.error("Failed to delete slide:", err);
      alert(`Error deleting presentation: ${err.message}`);
    }
  }

  function moveTemplateBlock(sourceIndex, targetIndex) {
    setTemplateBlocks((current) => {
      const blocks = [...current];
      const [moved] = blocks.splice(sourceIndex, 1);
      blocks.splice(targetIndex, 0, moved);
      return blocks;
    });
  }

  function handleTemplateDragStart(index) {
    setDragIndex(index);
  }

  function handleTemplateDragOver(event) {
    event.preventDefault();
  }

  function handleTemplateDrop(index) {
    if (dragIndex === null || dragIndex === index) {
      return;
    }
    moveTemplateBlock(dragIndex, index);
    setDragIndex(null);
  }

  function addTemplateSection(type, flavor = null, label = null) {
    const slots = buildTemplateSlots();
    if (templateBlocks.length >= 6) {
      setTemplateStatus("A template may contain at most 6 slides (cover, outline, theory, practical, image, end).");
      return;
    }
    if (type === "content" && !flavor) {
      setTemplateStatus("Content slides must be created as Theory or Practical.");
      return;
    }
    const key = slotKeyOf(type, flavor);
    if (slots.has(key)) {
      setTemplateStatus(`A "${label || key}" slide is already in the template — each of the 6 slide types can appear once.`);
      return;
    }
    const newBlock = {
      id: `${type}-${Date.now()}`,
      type,
      ...(flavor ? { flavor } : {}),
      title: type === "cover" ? "Presentation Title" : type === "end" ? "Thank You" : `New ${label || "Section"}`,
      subtitle: "Subtitle",
      backgroundColor: type === "cover" || type === "end" ? "#0B523E" : "#F0F7F2",
      textColor: type === "cover" || type === "end" ? "#FFFFFF" : "#0B523E",
      layout: type === "cover" || type === "end" ? "center" : "default",
      design: "minimal",
      elements: [],
    };
    setTemplateBlocks((current) => [...current, newBlock]);
    setTemplateStatus(`Added "${label || key}" slide.`);
  }

  function removeTemplateBlock(index) {
    setTemplateBlocks((current) => current.filter((_, idx) => idx !== index));
  }

  function loadDefaultTemplate() {
    setTemplateBlocks(defaultTemplateBlocks);
    setTemplateJson("");
    setTemplateStatus("Loaded default template builder layout.");
  }

  function quickCreateBasicSlides() {
    setTemplateBlocks([
      { id: `cover-${Date.now()}`, type: "cover", title: "Presentation Title", subtitle: "Subtitle here", backgroundColor: "#0B523E", textColor: "#FFFFFF", layout: "center", design: "modern", elements: [] },
      { id: `outline-${Date.now()}`, type: "outline", title: "Outline", subtitle: "Overview", backgroundColor: "#F0F7F2", textColor: "#0B523E", design: "minimal", elements: [] },
      { id: `theory-${Date.now()}`, type: "content", flavor: "theory", title: "Content Section", subtitle: "Details", backgroundColor: "#F0F7F2", textColor: "#0B523E", layout: "bullets", elements: [] },
      { id: `practical-${Date.now()}`, type: "content", flavor: "practical", title: "Practical Session", subtitle: "Hands-on activity", backgroundColor: "#F0F7F2", textColor: "#0B523E", layout: "default", elements: [] },
      { id: `image-${Date.now()}`, type: "image", title: "Image Slide", subtitle: "Visual content", backgroundColor: "#FFFFFF", textColor: "#0B523E", layout: "fullscreen", elements: [] },
      { id: `end-${Date.now()}`, type: "end", title: "Thank You", subtitle: "Questions & discussion", backgroundColor: "#0B523E", textColor: "#FFFFFF", design: "modern", elements: [] },
    ]);
    setTemplateStatus("Created the 6-slide template structure: Cover, Outline, Theory, Practical, Image, End");
  }

  function loadTemplateJsonIntoBuilder() {
    setTemplateError(null);
    let parsed = null;
    try {
      parsed = JSON.parse(templateJson.trim());
    } catch (err) {
      setTemplateError("Invalid JSON: " + err.message);
      setTemplateStatus("");
      return;
    }

    if (parsed.slide_order && Array.isArray(parsed.slide_order)) {
      const blocks = parsed.slide_order
        .filter((b) => ["cover", "outline", "content", "image", "end"].includes((b || {}).type || ""))
        .map((block) => ({
          id: block.id || `${block.type || "content"}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
          type: block.type || "content",
          flavor: block.type === "content" ? (block.flavor || "theory") : block.flavor || null,
          title: block.title || (block.type === "end" ? "Thank You" : "New Section"),
          subtitle: block.subtitle || "",
          backgroundColor: block.backgroundColor || (block.type === "cover" || block.type === "end" ? "#0B523E" : "#F0F7F2"),
          textColor: block.textColor || (block.type === "cover" || block.type === "end" ? "#FFFFFF" : "#0B523E"),
          layout: block.layout || "default",
          design: block.design || "minimal",
          elements: Array.isArray(block.elements) ? block.elements : [],
        }));
      const kept = blocks.slice(0, 6);
      if (blocks.length > 6) {
        setTemplateStatus(`Template JSON had ${blocks.length} slides; kept only the first 6 (cover, outline, theory, practical, image, end).`);
      }
      setTemplateBlocks(kept);
      setTemplateName(parsed.name || templateName);
      setTemplateDescription(parsed.description || templateDescription);
      setTemplateStatus("Template JSON loaded into the builder. Edit blocks or press Create Template.");
    } else {
      setTemplateError("JSON must contain a \"slide_order\" array.");
      setTemplateStatus("");
    }
  }

  function openInBuilder(template) {
    if (template && template.template_json) {
      setTemplateJson(JSON.stringify(template.template_json, null, 2));
      loadTemplateJsonIntoBuilder();
      setShowTemplatesModal(false);
      setTemplateTab("builder");
      setTemplateStatus(`Loaded template "${template.name}" into the builder.`);
    } else if (template) {
      setTemplateStatus(`Template "${template.name}" has no JSON blocks to edit; use the Upload tab.`);
    }
  }

  async function deleteTemplateById(id) {
    if (!confirm("Delete this template permanently?")) return;
    try {
      const response = await fetch(`${apiBase}/api/templates/${id}?user_id=${currentUserId}`, { method: "DELETE" });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || "Failed to delete template");
      }
      // loadTemplates reconciles the selection: it falls back to the first
      // remaining template, or to 0 once the list is empty.
      await loadTemplates();
    } catch (err) {
      setTemplatesModalError(err instanceof Error ? err.message : "Failed to delete template");
    }
  }

  async function loadUsers() {
    try {
      setUsersLoading(true);
      setUsersError(null);
      const response = await fetch(`${apiBase}/api/users?user_id=${currentUserId}`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `Failed to load users (${response.status})`);
      }
      setUsers(await response.json());
    } catch (err) {
      setUsersError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setUsersLoading(false);
    }
  }

  function openCreateUserModal() {
    setUserForm({ id: null, username: "", email: "", password: "", role: "user", is_active: true });
    setUserModalMode("create");
    setShowUserModal(true);
  }

  function openEditUserModal(user) {
    setUserForm({ id: user.id, username: user.username, email: user.email, password: "", role: user.role, is_active: user.is_active });
    setUserModalMode("edit");
    setShowUserModal(true);
  }

  async function submitUserForm() {
    try {
      const method = userModalMode === "create" ? "POST" : "PUT";
      const url = userModalMode === "create"
        ? `${apiBase}/api/users?user_id=${currentUserId}`
        : `${apiBase}/api/users/${userForm.id}?user_id=${currentUserId}`;
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(userForm),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to save user");
      setShowUserModal(false);
      await loadUsers();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to save user");
    }
  }

  async function toggleUserActive(user) {
    try {
      const response = await fetch(`${apiBase}/api/users/${user.id}?user_id=${currentUserId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ is_active: !user.is_active }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to toggle user status");
      await loadUsers();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to toggle user status");
    }
  }

  async function deleteUserById(user) {
    if (user.id === currentUserId) { window.alert("You cannot delete your own account here."); return; }
    if (!confirm(`Delete user "${user.username}" permanently?`)) return;
    try {
      const response = await fetch(`${apiBase}/api/users/${user.id}?user_id=${currentUserId}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to delete user");
      await loadUsers();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to delete user");
    }
  }

  async function loadLlmProviders() {
    try {
      setLlmLoading(true);
      setLlmError(null);
      const response = await fetch(`${apiBase}/api/llm-providers?user_id=${currentUserId}`);
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || `Failed to load providers (${response.status})`);
      }
      setLlmProviders(await response.json());
    } catch (err) {
      setLlmError(err instanceof Error ? err.message : "Failed to load providers");
    } finally {
      setLlmLoading(false);
    }
  }

  function openCreateProviderModal() {
    setProviderForm({
      id: null, name: "", provider_type: "openai", base_url: "", model: "",
      api_key: "", priority: 100, enabled: true, is_default: false, extra_json: "{}",
    });
    setProviderModalMode("create");
    setProviderTestResult(null);
    setShowProviderModal(true);
  }

  function openEditProviderModal(provider) {
    setProviderForm({
      id: provider.id,
      name: provider.name,
      provider_type: provider.provider_type,
      base_url: provider.base_url || "",
      model: provider.model,
      api_key: "",
      priority: provider.priority,
      enabled: provider.enabled,
      is_default: provider.is_default,
      extra_json: JSON.stringify(provider.extra_json || {}, null, 2),
    });
    setProviderModalMode("edit");
    setProviderTestResult(null);
    setShowProviderModal(true);
  }

  async function submitProviderForm() {
    let extra = {};
    try {
      extra = providerForm.extra_json ? JSON.parse(providerForm.extra_json) : {};
    } catch (err) {
      window.alert("extra_json must be valid JSON (or leave it as {}).");
      return;
    }
    const payload = {
      name: providerForm.name,
      provider_type: providerForm.provider_type,
      base_url: providerForm.base_url,
      model: providerForm.model,
      priority: Number(providerForm.priority) || 100,
      enabled: providerForm.enabled,
      is_default: providerForm.is_default,
      extra_json: extra,
    };
    if (providerForm.api_key) payload.api_key = providerForm.api_key;
    try {
      const method = providerModalMode === "create" ? "POST" : "PUT";
      const url = providerModalMode === "create"
        ? `${apiBase}/api/llm-providers?user_id=${currentUserId}`
        : `${apiBase}/api/llm-providers/${providerForm.id}?user_id=${currentUserId}`;
      const response = await fetch(url, {
        method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to save provider");
      setShowProviderModal(false);
      setProviderStatus(`Saved provider "${data.name}".`);
      await loadLlmProviders();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to save provider");
    }
  }

  async function deleteProvider(provider) {
    if (!confirm(`Delete provider "${provider.name}"?`)) return;
    try {
      const response = await fetch(`${apiBase}/api/llm-providers/${provider.id}?user_id=${currentUserId}`, { method: "DELETE" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to delete provider");
      await loadLlmProviders();
    } catch (err) {
      window.alert(err instanceof Error ? err.message : "Failed to delete provider");
    }
  }

  async function testProvider(provider) {
    setProviderTestResult({ id: provider.id, ok: null, message: "Testing…" });
    try {
      const response = await fetch(`${apiBase}/api/llm-providers/${provider.id}/test?user_id=${currentUserId}`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Test failed");
      setProviderTestResult({ id: provider.id, ok: true, message: `Reply: ${data.reply || "OK"}` });
    } catch (err) {
      setProviderTestResult({ id: provider.id, ok: false, message: err instanceof Error ? err.message : "Test failed" });
    }
  }

  async function saveProfile() {
    try {
      setProfileStatus("");
      setProfileError(null);
      const response = await fetch(`${apiBase}/api/profile/${currentUserId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentUser),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || "Failed to update profile");
      setCurrentUser((prev) => ({ ...prev, ...data }));
      setProfileStatus("Profile updated successfully.");
    } catch (err) {
      setProfileError(err instanceof Error ? err.message : "Failed to update profile");
    }
  }

  function renderHomePage() {
    return (
      <>
        <section className="grid">
          <div className="card">
            <h3>Configuration Dashboard</h3>
            <label>
              Slide Count: {slideCount}
              <input type="range" min="5" max="50" value={slideCount} onChange={(e) => setSlideCount(Number(e.target.value))} />
            </label>

            <label>
              Theory %: {theoryPercent}
              <input type="range" min="0" max="100" value={theoryPercent} onChange={(e) => setTheoryPercent(Number(e.target.value))} />
            </label>
            <p>Practical %: {practicalPercent}</p>

            <label>
              Image Density %: {imagePercent}
              <input type="range" min="0" max="100" value={imagePercent} onChange={(e) => setImagePercent(Number(e.target.value))} />
            </label>

            <label>
              Audience Level
              <select value={audienceLevel} onChange={(e) => setAudienceLevel(e.target.value)}>
                <option>Beginner</option>
                <option>Intermediate</option>
                <option>Expert</option>
              </select>
            </label>

            <label>
              Palette
              <select value={paletteId} onChange={(e) => setPaletteId(Number(e.target.value))}>
                {palettes.map((palette) => (
                  <option value={palette.id} key={palette.id}>{palette.name}</option>
                ))}
              </select>
            </label>
          </div>

          <PreviewCard
            slideCount={slideCount}
            theoryPercent={theoryPercent}
            imagePercent={imagePercent}
            wordCount={wordCount}
          />
        </section>

        <section className="card">
          <h3>Presentation Details</h3>
          <label>
            Presentation Title
            <input
              type="text"
              placeholder="Enter presentation title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
            />
          </label>

          <label>
            Choose Template
            <select value={templateId ?? 0} onChange={(e) => setTemplateId(Number(e.target.value))}>
              <option value={0}>Default Theme (system)</option>
              {templates.map((template) => (
                <option key={template.id} value={template.id}>{template.name}</option>
              ))}
            </select>
            <span className="field-hint">Templates come from the Templates page; the selected one styles the generated PPTX.</span>
            {templatesError && <p className="error">{templatesError}</p>}
          </label>

          <label>
            Content Source
            <div className="radio-group">
              <label>
                <input
                  type="radio"
                  name="contentType"
                  value="text"
                  checked={contentType === "text"}
                  onChange={() => setContentType("text")}
                />
                Text Input
              </label>
              <label>
                <input
                  type="radio"
                  name="contentType"
                  value="file"
                  checked={contentType === "file"}
                  onChange={() => setContentType("file")}
                />
                Upload File
              </label>
              <label>
                <input
                  type="radio"
                  name="contentType"
                  value="prompt"
                  checked={contentType === "prompt"}
                  onChange={() => setContentType("prompt")}
                />
                Prompt
              </label>
            </div>
          </label>

          {contentType === "text" && (
            <>
              <textarea
                rows="10"
                placeholder="Paste your source text here"
                value={text}
                onChange={(e) => setText(preserveTextStructure(e.target.value))}
              />
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginTop: '8px' }}>
                <button
                  onClick={() => setText(cleanText(text))}
                  style={{ fontSize: '12px', padding: '4px 8px' }}
                  disabled={!text.trim()}
                >
                  Clean Text
                </button>
                <p style={{ fontSize: '12px', color: '#666', margin: 0 }}>
                  Structure is preserved: line breaks, bullets and headings are kept as you paste them.
                </p>
              </div>
              <p>Words: {wordCount}</p>
            </>
          )}

          {contentType === "file" && (
            <label>
              Upload source file (.docx or .pdf)
              <input
                type="file"
                accept=".docx,.pdf"
                onChange={(e) => setContentFile(e.target.files[0])}
              />
            </label>
          )}

          {contentType === "prompt" && (
            <label>
              Prompt for AI content
              <textarea
                rows="8"
                placeholder="Write a prompt that describes the presentation you want generated"
                value={promptText}
                onChange={(e) => setPromptText(e.target.value)}
              />
            </label>
          )}

          <label>
            Logo URL (optional)
            <input
              type="url"
              placeholder="https://example.com/logo.png"
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.target.value)}
              disabled={!!logoFile}
            />
          </label>
          <label>
            Or Upload Logo (optional)
            <input
              type="file"
              accept="image/*"
              onChange={(e) => setLogoFile(e.target.files[0])}
              disabled={!!logoUrl}
            />
          </label>
        </section>

        <section className="card">
          <h3>Output & Download</h3>
          <div className="button-row">
            <button onClick={preview} disabled={!title.trim() || ((contentType === "text" && text.trim().length < 50) || (contentType === "file" && !contentFile) || (contentType === "prompt" && promptText.trim().length < 20))}>
              Preview Slides
            </button>
            <button onClick={generate} disabled={!title.trim() || ((contentType === "text" && text.trim().length < 50) || (contentType === "file" && !contentFile) || (contentType === "prompt" && promptText.trim().length < 20))}>
              Generate PPTX/PDF
            </button>
          </div>
          <p>Status: {status}</p>
          {error ? <p className="error">Error: {error}</p> : null}
          {downloadLinks.pptx && (
            <p>
              <a href={downloadLinks.pptx} target="_blank" rel="noreferrer">
                Download PPTX
              </a>
            </p>
          )}
          {downloadLinks.pdf && (
            <p>
              <a href={downloadLinks.pdf} target="_blank" rel="noreferrer">
                Download PDF
              </a>
            </p>
          )}
          <p>
            Note: enter at least 50 characters of text and a title so the backend can process your request.
          </p>
        </section>

        {previewSlides.length > 0 && (
          <section className="card preview-list">
            <h3>Slide Preview</h3>
            {previewSlides.map((slide) => (
              <article key={slide.slide_number} className="slide-preview">
                <h4>
                  {slide.slide_number}. {slide.title} ({slide.type})
                </h4>
                <ul>
                  {slide.bullets.map((bullet, index) => (
                    <li key={index}>{bullet}</li>
                  ))}
                </ul>
              </article>
            ))}
          </section>
        )}
      </>
    );
  }

  function renderMySlidesPage() {
    return (
      <section className="card">
        <h3>My Slides</h3>
        {userSlidesLoading && <p>Loading slides...</p>}
        {userSlidesError && <p className="error">Error: {userSlidesError}</p>}
        {!userSlidesLoading && !userSlidesError && userSlides.length === 0 && <p>No slides found. Create some presentations first!</p>}
        <div className="slides-grid">
          {userSlides.map((slide) => (
            <div key={slide.id} className="slide-card">
              <div className="slide-content">
                <h4>{slide.title}</h4>
                <p><strong>User:</strong> {slide.user_name} ({slide.user_email})</p>
                <p><strong>Status:</strong> {slide.status}</p>
                <p><strong>Created:</strong> {slide.created_at ? new Date(slide.created_at).toLocaleString() : 'Unknown'}</p>
                {slide.file_path && (
                  <div className="download-buttons">
                    <button onClick={() => window.open(`${apiBase}/api/presentations/${slide.id}/download/pptx`, '_blank')} className="download-btn pptx-btn">
                      Download PPTX
                    </button>
                    <button onClick={() => window.open(`${apiBase}/api/presentations/${slide.id}/download/pdf`, '_blank')} className="download-btn pdf-btn">
                      Download PDF
                    </button>
                  </div>
                )}
              </div>
              <div className="slide-actions">
                <button onClick={() => deleteSlide(slide.id)} className="delete-btn">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      </section>
    );
  }

  async function createTemplate() {
    setTemplateError(null);
    setTemplateStatus("Creating template...");

    if (!templateName.trim()) {
      setTemplateError("Template name is required.");
      setTemplateStatus("");
      return;
    }

    const formData = new FormData();
    formData.append('user_id', '1');
    formData.append('name', templateName);
    formData.append('description', templateDescription);

    if (!templateFileUpload && templateBlocks.length > 6) {
      setTemplateError("A template may contain at most 6 slides (cover, outline, theory, practical, image, end).");
      setTemplateStatus("");
      return;
    }

    let payloadJson = templateJson.trim();
    if (!payloadJson && templateBlocks.length > 0) {
      payloadJson = JSON.stringify({
        name: templateName,
        description: templateDescription,
        styles: {
          primary: "#0B523E",
          secondary: "#147A45",
          accent: "#D4A01E",
          background: "#F0F7F2",
          text: "#2C2C2C",
        },
        footer_text: "REPUBLIC OF CAMEROON | Peace – Work – Fatherland",
        slide_order: templateBlocks,
      }, null, 2);
    }

    if (payloadJson) {
      formData.append('template_json', payloadJson);
    }
    if (templateFileUpload) {
      formData.append('template_file', templateFileUpload);
    }

    try {
      const response = await fetch(`${apiBase}/api/templates`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || data.message || 'Template creation failed');
      }

      const created = await response.json();
      setTemplateStatus(`Template created: ${created.name}`);
      setTemplateName("");
      setTemplateDescription("");
      setTemplateJson("");
      setTemplateFileUpload(null);
      setTemplateBlocks(defaultTemplateBlocks);
      await loadTemplates();
    } catch (err) {
      setTemplateError(err instanceof Error ? err.message : 'Failed to create template');
      setTemplateStatus("");
    }
  }

  function renderTemplatesModal() {
    return (
      <div className="modal-overlay" onClick={() => setShowTemplatesModal(false)}>
        <div className="modal" onClick={(e) => e.stopPropagation()}>
          <div className="modal-header">
            <h3>Saved Templates</h3>
            <button className="modal-close" onClick={() => setShowTemplatesModal(false)}>×</button>
          </div>
          {templatesModalError && <p className="error">{templatesModalError}</p>}
          {templates.length === 0 && <p>No templates available yet.</p>}
          <div className="saved-template-list">
            {templates.map((template) => (
              <div key={template.id} className="template-card">
                <div className="template-card-row">
                  <div>
                    <h4>{template.name}</h4>
                    <p>{template.description || 'No description provided.'}</p>
                    <span className="template-meta">
                      {template.id === Number(templateId) ? "⭐ Default in use" : ""} {template.created_by ? `by ${template.created_by}` : ""}
                    </span>
                  </div>
                  <div className="button-row">
                    {template.template_json ? (
                      <button onClick={() => openInBuilder(template)}>Edit</button>
                    ) : (
                      <span className="template-meta">(file-based only)</span>
                    )}
                    <button className="danger" onClick={() => deleteTemplateById(template.id)}>Delete</button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  function renderTemplateAdminPage() {
    return (
      <section className="card template-admin">
        <div className="template-admin-top">
          <div>
            <h3>Admin Templates</h3>
            <p>Build a template with the ribbon tools, or upload a 6-slide PPTX to use as section backgrounds.</p>
          </div>
          <div className="button-row">
            <button onClick={() => { loadDefaultTemplate(); setTemplateTab("builder"); }}>Load Default Theme</button>
            <button onClick={() => { loadTemplates(); setShowTemplatesModal(true); }}>Saved Templates</button>
          </div>
        </div>

        <div className="template-tabs">
          <button
            className={templateTab === "builder" ? "tab active" : "tab"}
            onClick={() => setTemplateTab("builder")}
          >Template Builder</button>
          <button
            className={templateTab === "upload" ? "tab active" : "tab"}
            onClick={() => setTemplateTab("upload")}
          >Upload Template</button>
        </div>

        {templateTab === "builder" && (
          <>
            <div className="ribbon">
              {ribbonTools.map((tool) => (
                <button
                  key={tool.label}
                  className="ribbon-tool"
                  draggable
                  onDragStart={(e) => { setDragTool(tool); e.dataTransfer.effectAllowed = "copy"; }}
                  onDragEnd={() => setDragTool(null)}
                  onClick={() => addTemplateSection(tool.type, tool.flavor, tool.label)}
                >
                  {tool.label}
                </button>
              ))}
              <span className="ribbon-hint">Drag a tool onto the list below or click to add.</span>
            </div>

            <div className="template-builder-grid">
              <div className="template-builder-panel">
                <label>
                  Template Name
                  <input
                    type="text"
                    placeholder="Template name"
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                </label>
                <label>
                  Description
                  <input
                    type="text"
                    placeholder="Template description"
                    value={templateDescription}
                    onChange={(e) => setTemplateDescription(e.target.value)}
                  />
                </label>

                <div className="template-actions-row">
                  <button type="button" onClick={quickCreateBasicSlides} style={{ minWidth: "160px", fontWeight: "bold" }}>🚀 Quick Create 6 Slides</button>
                  <button type="button" onClick={() => addTemplateSection('cover')}>+ Cover</button>
                  <button type="button" onClick={() => addTemplateSection('outline')}>+ Outline</button>
                  <button type="button" onClick={() => addTemplateSection('content', 'theory')}>+ Theory</button>
                  <button type="button" onClick={() => addTemplateSection('content', 'practical')}>+ Practical</button>
                  <button type="button" onClick={() => addTemplateSection('image')}>+ Image</button>
                  <button type="button" onClick={() => addTemplateSection('end')}>+ End</button>
                </div>

                <div
                  className="template-block-list"
                  onDragOver={(e) => { if (dragTool) e.preventDefault(); }}
                  onDrop={(e) => {
                    if (dragTool) {
                      e.preventDefault();
                      addTemplateSection(dragTool.type, dragTool.flavor, dragTool.label);
                      setDragTool(null);
                    }
                  }}
                >
                  {templateBlocks.map((block, index) => (
                    <div
                      className={`template-block ${dragIndex === index ? 'dragging' : ''}`}
                      key={block.id}
                      draggable
                      onDragStart={() => handleTemplateDragStart(index)}
                      onDragOver={handleTemplateDragOver}
                      onDrop={() => handleTemplateDrop(index)}
                    >
                      <div className="template-block-header">
                        <strong>{block.type.toUpperCase()}{block.flavor ? ` · ${block.flavor}` : ""}</strong>
                        <button type="button" onClick={() => removeTemplateBlock(index)}>Remove</button>
                      </div>

                      <div
                        className={`slide-canvas ${armedPencil ? "drawing" : ""} ${drawPreview && drawPreview.block === index ? "drawing" : ""}`}
                        style={{ backgroundColor: block.backgroundColor || "#F0F7F2" }}
                        draggable={false}
                        onDragOver={(e) => { if (dragToolItem) e.preventDefault(); }}
                        onDrop={(e) => {
                          if (dragToolItem) {
                            e.preventDefault();
                            dropElementOnBlock(index, e);
                          }
                        }}
                        onPointerDown={(e) => canvasDrawStart(e, index)}
                        onPointerMove={canvasDrawMove}
                        onPointerUp={canvasDrawEnd}
                        onClick={() => {
                          if (armedPencil) return;
                          setSelectedBlock(index);
                          setSelectedElement(null);
                        }}
                      >
                        <div className="slide-canvas-label">{block.type.toUpperCase()}{block.flavor ? ` · ${block.flavor}` : ""} — click/shape area</div>
                        {(block.elements || []).map((el) => {
                          const isSel = selectedBlock === index && selectedElement === el.id;
                          const isTransparent = !el.fill || el.fill === "transparent" || el.fill === "none";
                          const isShape = !["text", "line", "pencil", "image"].includes(el.type);
                          const textColor = el.type === "text" ? contrastText(el.fill || "#FFFFFF") : "#1A1A1A";
                          const outlineBorder = el.outline_color && Number(el.outline_width) > 0;
                          const style = {
                            left: `${el.x}%`,
                            top: `${el.y}%`,
                            width: `${el.w}%`,
                            height: `${el.h}%`,
                            ...(el.rotation ? { transform: `rotate(${el.rotation}deg)` } : {}),
                            ...(!isShape || el.type === "text"
                              ? { backgroundColor: isTransparent ? "transparent" : (el.fill || "rgba(0,0,0,0.12)") }
                              : {}),
                            ...(!isShape && outlineBorder
                              ? { border: `${el.outline_width}px solid ${el.outline_color}` }
                              : {}),
                          };
                          return (
                            <div
                              key={el.id}
                              className={`canvas-element ${isSel ? "selected" : ""} el-${el.type}`}
                              style={style}
                              draggable={false}
                              onPointerDown={(e) => elementPointerDown(e, index, el.id)}
                              onPointerMove={(e) => elementPointerMove(e, index, el.id)}
                              onPointerUp={elementPointerUp}
                              onClick={(e) => {
                                e.stopPropagation();
                                if (armedPencil) {
                                  setArmedPencil(false);
                                  return;
                                }
                                setSelectedBlock(index);
                                setSelectedElement(el.id);
                              }}
                              onDoubleClick={() => {
                                if (el.type === "text") {
                                  const t = window.prompt("Text area content", el.text || "");
                                  if (t !== null) updateBlockElement(index, el.id, { text: t });
                                }
                              }}
                            >
                              {isShape && (
                                <svg
                                  className="canvas-shape-svg"
                                  viewBox="0 0 100 100"
                                  preserveAspectRatio="none"
                                  style={{ pointerEvents: "none" }}
                                >
                                  <path
                                    d={shapeSVGPath(el.type)}
                                    fill={isTransparent ? "none" : (el.fill || "none")}
                                    stroke={outlineBorder ? el.outline_color : "none"}
                                    strokeWidth={outlineBorder ? Number(el.outline_width) : 0}
                                    vectorEffect="non-scaling-stroke"
                                    strokeLinejoin="round"
                                    strokeLinecap="round"
                                  />
                                </svg>
                              )}
                              {el.type === "pencil" ? (
                                <svg className="canvas-pencil" viewBox="0 0 100 100" preserveAspectRatio="none">
                                  <path
                                    d={pencilPath(el.points)}
                                    fill="none"
                                    stroke={el.stroke_color || "#0B523E"}
                                    strokeWidth={Math.max(1, el.stroke_width || 3)}
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                  />
                                </svg>
                              ) : (
                                !isShape && (
                                  <span className="canvas-element-text" style={{ color: textColor }}>
                                    {el.type === "text" ? (el.text || "Text area") : ""}
                                  </span>
                                )
                              )}
                              {isSel && (
                                <>
                                  <span
                                    className="canvas-element-remove"
                                    onPointerDown={(e) => e.stopPropagation()}
                                    onClick={(e) => { e.stopPropagation(); removeBlockElement(index, el.id); }}
                                    title="Delete (or press Delete key)"
                                  >×</span>
                                  <span
                                    className="canvas-rotate-handle"
                                    draggable={false}
                                    onPointerDown={(e) => elementRotateStart(e, index, el.id)}
                                    onPointerMove={(e) => elementPointerMove(e, index, el.id)}
                                    onPointerUp={elementPointerUp}
                                    title={`Rotate (${Math.round(Number(el.rotation) || 0)}°)`}
                                  >⟳</span>
                                  {RESIZE_HANDLES.map((h) => (
                                    <span
                                      key={h}
                                      className={`canvas-element-resize rh-${h}`}
                                      draggable={false}
                                      onPointerDown={(e) => elementResizeStart(e, index, el.id, h)}
                                      onPointerMove={(e) => elementPointerMove(e, index, el.id)}
                                      onPointerUp={elementPointerUp}
                                      title={h === "se" ? "Drag to resize" : h}
                                    />
                                  ))}
                                </>
                              )}
                            </div>
                          );
                        })}
                        {drawPreview && drawPreview.block === index && (
                          <svg className="canvas-pencil canvas-preview" viewBox="0 0 100 100" preserveAspectRatio="none">
                            <path
                              d={pencilPath(drawPreview.points)}
                              fill="none"
                              stroke={drawPreview.stroke_color}
                              strokeWidth={Math.max(1, drawPreview.stroke_width * 2)}
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              opacity="0.7"
                            />
                          </svg>
                        )}
                        {!(block.elements || []).length && !drawPreview && (
                          <div className="slide-canvas-empty">Drag a tool from the toolbox or click one to add.</div>
                        )}
                      </div>

                      {selectedBlock === index && selectedElement && (() => {
                        const el = (block.elements || []).find((e) => e.id === selectedElement);
                        if (!el) return null;
                        return (
                          <div className="element-editor">
                            <strong>Element: {el.type}{el.type === "pencil" ? ` · ${(el.points || []).length} points` : ""}</strong>
                            <div className="element-editor-row">
                              <label>X <input type="number" min="0" max="100" value={Math.round(el.x)}
                                onChange={(e) => updateBlockElement(index, el.id, { x: Number(e.target.value) || 0 })} /></label>
                              <label>Y <input type="number" min="0" max="100" value={Math.round(el.y)}
                                onChange={(e) => updateBlockElement(index, el.id, { y: Number(e.target.value) || 0 })} /></label>
                              <label>W <input type="number" min="2" max="100" value={Math.round(el.w)}
                                onChange={(e) => updateBlockElement(index, el.id, { w: Number(e.target.value) || 2 })} /></label>
                              <label>H <input type="number" min="2" max="100" value={Math.round(el.h)}
                                onChange={(e) => updateBlockElement(index, el.id, { h: Number(e.target.value) || 2 })} /></label>
                              <label>Angle
                                <input type="number" min="-360" max="360" value={Math.round(Number(el.rotation) || 0)}
                                  onChange={(e) => updateBlockElement(index, el.id, { rotation: (Number(e.target.value) || 0) % 360 })} />
                              </label>
                              {el.type !== "pencil" && (
                                <label>Fill
                                  <input type="color" value={(el.fill && el.fill !== "transparent" && el.fill !== "none") ? el.fill : "#147A45"}
                                    onChange={(e) => updateBlockElement(index, el.id, { fill: e.target.value })} />
                                </label>
                              )}
                              {el.type !== "pencil" && el.type !== "line" && (
                                <label className="fill-none">
                                  <input
                                    type="checkbox"
                                    checked={(el.fill === "transparent" || el.fill === "none")}
                                    onChange={(e) => updateBlockElement(index, el.id, { fill: e.target.checked ? "transparent" : "#147A45" })}
                                  />
                                  No fill
                                </label>
                              )}
                            </div>
                            {(el.type === "pencil" || el.type === "line") ? (
                              <div className="element-editor-row">
                                <label>Stroke/color
                                  <input type="color" value={(el.stroke_color || el.fill || "#0B523E")}
                                    onChange={(e) => updateBlockElement(index, el.id, { stroke_color: e.target.value, fill: e.target.value })} />
                                </label>
                                <label>Thickness
                                  <input type="number" min="1" max="24" value={(el.stroke_width || 3)}
                                    onChange={(e) => updateBlockElement(index, el.id, { stroke_width: Math.max(1, Number(e.target.value) || 1) })} />
                                </label>
                              </div>
                            ) : (
                              <div className="element-editor-row">
                                <label>Border color
                                  <input type="color" value={el.outline_color || "#0B523E"}
                                    onChange={(e) => updateBlockElement(index, el.id, { outline_color: e.target.value })} />
                                </label>
                                <label>Border thickness
                                  <input type="number" min="0" max="24" value={Number(el.outline_width || 0)}
                                    onChange={(e) => updateBlockElement(index, el.id, { outline_width: Math.max(0, Number(e.target.value) || 0) })} />
                                </label>
                              </div>
                            )}
                            {el.type === "text" && (
                              <label>Text
                                <input type="text" value={el.text || ""}
                                  onChange={(e) => updateBlockElement(index, el.id, { text: e.target.value })} />
                              </label>
                            )}
                          </div>
                        );
                      })()}

                      <div className="template-block-design-row">
                        <label>
                          Background
                          <input
                            type="color"
                            value={block.backgroundColor || "#F0F7F2"}
                            onChange={(e) => {
                              const updated = [...templateBlocks];
                              updated[index] = { ...updated[index], backgroundColor: e.target.value };
                              setTemplateBlocks(updated);
                            }}
                          />
                        </label>
                        <label>
                          Text Color
                          <input
                            type="color"
                            value={block.textColor || "#0B523E"}
                            onChange={(e) => {
                              const updated = [...templateBlocks];
                              updated[index] = { ...updated[index], textColor: e.target.value };
                              setTemplateBlocks(updated);
                            }}
                          />
                        </label>
                        {block.type === "content" && (
                          <label>
                            Type
                            <select
                              value={block.flavor || 'theory'}
                              onChange={(e) => {
                                const updated = [...templateBlocks];
                                updated[index] = { ...updated[index], flavor: e.target.value };
                                setTemplateBlocks(updated);
                              }}
                            >
                              <option value="theory">Theory</option>
                              <option value="practical">Practical</option>
                            </select>
                          </label>
                        )}
                        {!["cover", "outline", "end"].includes(block.type) && (
                          <label>
                            Layout
                            <select
                              value={block.layout || 'default'}
                              onChange={(e) => {
                                const updated = [...templateBlocks];
                                updated[index] = { ...updated[index], layout: e.target.value };
                                setTemplateBlocks(updated);
                              }}
                            >
                              <option value="default">Default</option>
                              <option value="bullets">Bullet Points</option>
                              <option value="image-right">Image Right</option>
                              <option value="image-left">Image Left</option>
                              <option value="fullscreen">Full Screen Image</option>
                              <option value="two-column">Two Column</option>
                              <option value="full-width">Full Width</option>
                            </select>
                          </label>
                        )}
                        <label>
                          Design
                          <select
                            value={block.design || 'minimal'}
                            onChange={(e) => {
                              const updated = [...templateBlocks];
                              updated[index] = { ...updated[index], design: e.target.value };
                              setTemplateBlocks(updated);
                            }}
                          >
                            <option value="minimal">Minimal</option>
                            <option value="modern">Modern</option>
                            <option value="corporate">Corporate</option>
                            <option value="colorful">Colorful</option>
                            <option value="gradient">Gradient</option>
                          </select>
                        </label>
                      </div>
                    </div>
                  ))}
                </div>

                <label>
                  Template JSON
                  <textarea
                    rows="8"
                    placeholder='Paste template JSON here or click Save builder to generate JSON from blocks.'
                    value={templateJson}
                    onChange={(e) => setTemplateJson(e.target.value)}
                  />
                </label>
                <div className="button-row">
                  <button type="button" onClick={() => {
                    setTemplateJson(JSON.stringify({
                      name: templateName || 'Untitled template',
                      description: templateDescription,
                      styles: {
                        primary: "#0B523E",
                        secondary: "#147A45",
                        accent: "#D4A01E",
                        background: "#F0F7F2",
                        text: "#2C2C2C",
                      },
                      footer_text: "REPUBLIC OF CAMEROON | Peace – Work – Fatherland",
                      slide_order: templateBlocks,
                    }, null, 2));
                    setTemplateStatus('Template JSON generated from builder.');
                  }}>
                    Save Builder to JSON
                  </button>
                  <button type="button" onClick={loadTemplateJsonIntoBuilder}>Load JSON into Builder</button>
                  <button type="button" onClick={createTemplate}>Create Template</button>
                </div>
              </div>

              <div className="template-preview-panel">
                {templateStatus && <p className="success">{templateStatus}</p>}
                {templateError && <p className="error">{templateError}</p>}
                {templates.length > 0 && (
                  <div className="template-list">
                    <h4>Current default: {templates.find((t) => String(t.id) === String(templateId))?.name || "None"}</h4>
                  </div>
                )}

                <div className="toolbox">
                  <h4>🔧 Slide Tools</h4>
                  <p className="toolbox-hint">Drag a tool onto a slide canvas, or click to add it to the selected slide.</p>
                  {basicTools.map((tool) => (
                    <button
                      key={tool.id}
                      className={`toolbox-tool ${tool.id === "pencil" && armedPencil ? "armed" : ""}`}
                      draggable
                      onDragStart={(e) => { setDragToolItem(tool.id); e.dataTransfer.effectAllowed = "copy"; }}
                      onDragEnd={() => setDragToolItem(null)}
                      onClick={() => {
                        if (tool.id === "pencil") {
                          setArmedPencil((v) => !v);
                          return;
                        }
                        const target = selectedBlock !== null && selectedBlock < templateBlocks.length
                          ? selectedBlock
                          : templateBlocks.length - 1;
                        if (templateBlocks[target]) addBlockElement(target, tool.id);
                      }}
                    >
                      {tool.label}
                    </button>
                  ))}
                  <h4 className="toolbox-group-title">⬛ Shapes</h4>
                  <div className="toolbox-shape-grid">
                    {shapeTools.map((tool) => (
                      <button
                        key={tool.id}
                        className="toolbox-tool toolbox-shape"
                        draggable
                        onDragStart={(e) => { setDragToolItem(tool.id); e.dataTransfer.effectAllowed = "copy"; }}
                        onDragEnd={() => setDragToolItem(null)}
                        onClick={() => {
                          const target = selectedBlock !== null && selectedBlock < templateBlocks.length
                            ? selectedBlock
                            : templateBlocks.length - 1;
                          if (templateBlocks[target]) addBlockElement(target, tool.id);
                        }}
                      >
                        {tool.label}
                      </button>
                    ))}
                  </div>
                  {armedPencil && (
                    <div className="pencil-options">
                      <label>Line thickness
                        <input type="number" min="1" max="20" value={pencilTool.stroke_width}
                          onChange={(e) => setPencilTool({ ...pencilTool, stroke_width: Math.max(1, Number(e.target.value) || 1) })} />
                      </label>
                      <label>Line color
                        <input type="color" value={pencilTool.stroke_color}
                          onChange={(e) => setPencilTool({ ...pencilTool, stroke_color: e.target.value })} />
                      </label>
                      <button onClick={() => setArmedPencil(false)}>Done drawing</button>
                    </div>
                  )}
                  <p className="toolbox-hint">{selectedBlock !== null && templateBlocks[selectedBlock]
                    ? `Adding to: ${templateBlocks[selectedBlock].type.toUpperCase()}${templateBlocks[selectedBlock].flavor ? ` ${templateBlocks[selectedBlock].flavor}` : ""}`
                    : "No slide selected yet — click a canvas first."}</p>
                </div>
              </div>
            </div>
          </>
        )}

        {templateTab === "upload" && (
          <div className="upload-panel">
            <div className="upload-instructions">
              <h4>Upload a 6-slide PPTX as section backgrounds</h4>
              <ol>
                <li><strong>Slide 1</strong> — Cover</li>
                <li><strong>Slide 2</strong> — Outline</li>
                <li><strong>Slide 3</strong> — Theory content slide</li>
                <li><strong>Slide 4</strong> — Practical content slide</li>
                <li><strong>Slide 5</strong> — Image / diagram slide</li>
                <li><strong>Slide 6</strong> — End / thank-you slide</li>
              </ol>
              <p>Each slide is rendered to a background image and your generated content slides use it as a base. Design anything you like, but leave space for the content text.</p>
              {templateFileUpload && templateFileUpload.name.endsWith('.pptx') && (
                <p className="success">Ready to upload: {templateFileUpload.name} (6 slides expected)</p>
              )}
            </div>
            <label>
              PPTX file (6 slides)
              <input
                type="file"
                accept=".pptx"
                onChange={(e) => setTemplateFileUpload(e.target.files[0])}
              />
            </label>
            <label>
              Template Name
              <input
                type="text"
                placeholder="e.g. District Office Branded Theme"
                value={templateName}
                onChange={(e) => setTemplateName(e.target.value)}
              />
            </label>
            <label>
              Description
              <input
                type="text"
                placeholder="Describe this template"
                value={templateDescription}
                onChange={(e) => setTemplateDescription(e.target.value)}
              />
            </label>
            <div className="button-row">
              <button
                type="button"
                disabled={!templateFileUpload}
                onClick={() => {
                  setTemplateJson("");
                  createTemplate();
                }}
              >Upload as Template</button>
              <button type="button" onClick={() => setTemplateFileUpload(null)}>Clear file</button>
            </div>
            {templateStatus && <p className="success">{templateStatus}</p>}
            {templateError && <p className="error">{templateError}</p>}
          </div>
        )}

        {showTemplatesModal && renderTemplatesModal()}
      </section>
    );
  }

  function renderContactPage() {
    return (
      <section className="card">
        <h3>Contact Us</h3>
        <p>For support, contact the super user:</p>
        <p>Email: admin@slidemaka.com</p>
        <p>Phone: +1-234-567-8900</p>
      </section>
    );
  }

  function renderUsersPage() {
    return (
      <section className="card">
        <div className="template-admin-top">
          <div>
            <h3>User Management</h3>
            <p>Manage accounts, roles (admin / admin1 / user) and activation status.</p>
          </div>
          <div className="button-row">
            <button onClick={openCreateUserModal}>+ Create User</button>
            <button onClick={loadUsers}>Refresh</button>
          </div>
        </div>
        {usersError && <p className="error">{usersError}</p>}
        {usersLoading && <p>Loading users…</p>}
        <div className="user-tiles">
          {users.map((user) => (
            <div key={user.id} className={`user-tile ${user.is_active === false ? "inactive" : ""}`}>
              <div className="user-tile-head">
                <strong>{user.username}</strong>
                {user.id === currentUserId && <span className="badge">You</span>}
                <span className={`role-badge role-${user.role}`}>{user.role}</span>
                {user.is_active === false && <span className="badge danger">Deactivated</span>}
              </div>
              <p className="user-tile-email">{user.email || "—"}</p>
              <div className="button-row">
                <button onClick={() => openEditUserModal(user)}>Edit</button>
                <button onClick={() => toggleUserActive(user)}>
                  {user.is_active === false ? "Activate" : "Deactivate"}
                </button>
                <button className="danger" onClick={() => deleteUserById(user)}>Delete</button>
              </div>
            </div>
          ))}
        </div>
        {showUserModal && (
          <div className="modal-overlay" onClick={() => setShowUserModal(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>{userModalMode === "create" ? "Create User" : `Edit ${userForm.username}`}</h3>
                <button className="modal-close" onClick={() => setShowUserModal(false)}>×</button>
              </div>
              <label>
                Username
                <input
                  type="text"
                  value={userForm.username}
                  onChange={(e) => setUserForm({ ...userForm, username: e.target.value })}
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  value={userForm.email}
                  onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
                />
              </label>
              {userModalMode === "create" && (
                <label>
                  Password
                  <input
                    type="password"
                    value={userForm.password}
                    onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
                  />
                </label>
              )}
              <label>
                Role
                <select
                  value={userForm.role}
                  onChange={(e) => setUserForm({ ...userForm, role: e.target.value })}
                >
                  <option value="user">user</option>
                  <option value="admin1">admin1</option>
                  <option value="admin">admin</option>
                </select>
              </label>
              <label>
                Active
                <select
                  value={userForm.is_active ? "1" : "0"}
                  onChange={(e) => setUserForm({ ...userForm, is_active: e.target.value === "1" })}
                >
                  <option value="1">Active</option>
                  <option value="0">Deactivated</option>
                </select>
              </label>
              <div className="button-row">
                <button onClick={submitUserForm}>Save</button>
                <button onClick={() => setShowUserModal(false)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </section>
    );
  }

  function renderLlmProvidersPage() {
    return (
      <section className="card">
        <div className="template-admin-top">
          <div>
            <h3>LLM Providers</h3>
            <p>
              Tasks are routed to the enabled providers in priority order, falling back to the
              built-in Gemini client. Add any OpenAI-compatible endpoint (OpenAI, OpenRouter, Groq,
              Ollama, LM Studio…), Anthropic Claude, or another Gemini key.
            </p>
          </div>
          <div className="button-row">
            <button onClick={openCreateProviderModal}>+ Add Provider</button>
            <button onClick={loadLlmProviders}>Refresh</button>
          </div>
        </div>
        {providerStatus && <p className="success">{providerStatus}</p>}
        {llmError && <p className="error">{llmError}</p>}
        {llmLoading && <p>Loading providers…</p>}
        <div className="user-tiles">
          {llmProviders.map((provider) => (
            <div key={provider.id} className={`user-tile ${provider.enabled === false ? "inactive" : ""}`}>
              <div className="user-tile-head">
                <strong>{provider.name}</strong>
                <span className="badge">{provider.provider_type}</span>
                {provider.is_default && <span className="badge">fallback</span>}
                {provider.enabled === false && <span className="badge danger">disabled</span>}
              </div>
              <p className="user-tile-email">{provider.model} · priority {provider.priority}</p>
              <p className="user-tile-email">{provider.base_url || "default endpoint"}</p>
              <div className="button-row">
                <button onClick={() => openEditProviderModal(provider)}>Edit</button>
                <button onClick={() => testProvider(provider)}>Test</button>
                <button className="danger" onClick={() => deleteProvider(provider)}>Delete</button>
              </div>
              {providerTestResult && providerTestResult.id === provider.id && (
                <p className={providerTestResult.ok === false ? "error" : "success"}>{providerTestResult.message}</p>
              )}
            </div>
          ))}
        </div>
        {showProviderModal && (
          <div className="modal-overlay" onClick={() => setShowProviderModal(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <h3>{providerModalMode === "create" ? "Add LLM Provider" : `Edit ${providerForm.name}`}</h3>
                <button className="modal-close" onClick={() => setShowProviderModal(false)}>×</button>
              </div>
              <label>
                Name
                <input
                  type="text"
                  value={providerForm.name}
                  onChange={(e) => setProviderForm({ ...providerForm, name: e.target.value })}
                />
              </label>
              <label>
                Type
                <select
                  value={providerForm.provider_type}
                  onChange={(e) => setProviderForm({ ...providerForm, provider_type: e.target.value })}
                >
                  <option value="openai">OpenAI-compatible</option>
                  <option value="anthropic">Anthropic Claude</option>
                  <option value="gemini">Google Gemini</option>
                </select>
              </label>
              <label>
                Base URL (blank = vendor default)
                <input
                  type="text"
                  placeholder="https://api.openai.com/v1"
                  value={providerForm.base_url}
                  onChange={(e) => setProviderForm({ ...providerForm, base_url: e.target.value })}
                />
              </label>
              <label>
                Model
                <input
                  type="text"
                  placeholder="gpt-4o-mini / claude-3-5-sonnet-latest / gemini-3.5-flash"
                  value={providerForm.model}
                  onChange={(e) => setProviderForm({ ...providerForm, model: e.target.value })}
                />
              </label>
              <label>
                API key {providerModalMode === "edit" && "(leave blank to keep current)"}
                <input
                  type="password"
                  value={providerForm.api_key}
                  onChange={(e) => setProviderForm({ ...providerForm, api_key: e.target.value })}
                />
              </label>
              <label>
                Priority (lower = tried first)
                <input
                  type="number"
                  value={providerForm.priority}
                  onChange={(e) => setProviderForm({ ...providerForm, priority: e.target.value })}
                />
              </label>
              <label>
                extra_json (optional: {"{\"tasks\":[\"visual_plan\"]}"})
                <textarea
                  rows={3}
                  value={providerForm.extra_json}
                  onChange={(e) => setProviderForm({ ...providerForm, extra_json: e.target.value })}
                />
              </label>
              <label>
                Enabled
                <select
                  value={providerForm.enabled ? "1" : "0"}
                  onChange={(e) => setProviderForm({ ...providerForm, enabled: e.target.value === "1" })}
                >
                  <option value="1">Enabled</option>
                  <option value="0">Disabled</option>
                </select>
              </label>
              <div className="button-row">
                <button onClick={submitProviderForm}>Save</button>
                <button onClick={() => setShowProviderModal(false)}>Cancel</button>
              </div>
            </div>
          </div>
        )}
      </section>
    );
  }

  function renderAccountPage() {
    return (
      <section className="card">
        <h3>Account</h3>
        <p>Update your profile below.</p>

        <div className="profile-tile">
          <div className="profile-avatar">{(currentUser.username || "U").charAt(0).toUpperCase()}</div>
          <input
            type="text"
            placeholder="Username"
            value={currentUser.username}
            onChange={(e) => setCurrentUser({ ...currentUser, username: e.target.value })}
          />
          <input
            type="email"
            placeholder="Email"
            value={currentUser.email}
            onChange={(e) => setCurrentUser({ ...currentUser, email: e.target.value })}
          />
          {hasAdminRights && (
            <label>
              Role
              <select
                value={currentUser.role}
                onChange={(e) => setCurrentUser({ ...currentUser, role: e.target.value })}
              >
                <option value="user">user</option>
                <option value="admin1">admin1</option>
                <option value="admin">admin</option>
              </select>
            </label>
          )}
          <label>
            New password
            <input
              type="password"
              placeholder="Leave blank to keep current"
              value={currentUser.new_password || ""}
              onChange={(e) => setCurrentUser({ ...currentUser, new_password: e.target.value, current_password: e.target.value ? (currentUser.current_password || "") : "" })}
            />
          </label>
          <label>
            Current password (required to change password)
            <input
              type="password"
              placeholder="Current password"
              value={currentUser.current_password || ""}
              onChange={(e) => setCurrentUser({ ...currentUser, current_password: e.target.value })}
            />
          </label>
          <div className="button-row">
            <button onClick={saveProfile}>Save Profile</button>
          </div>
          {profileStatus && <p className="success">{profileStatus}</p>}
          {profileError && <p className="error">{profileError}</p>}
        </div>

        <div className="profile-tile logout-tile">
          <strong>Session</strong>
          <p>Signed in as <em>{currentUser.username}</em> (ID {currentUserId}).</p>
          <button
            className="danger"
            onClick={() => {
              setCurrentPage("home");
              setUserSlides([]);
              setPreviewSlides([]);
              setDownloadLinks({ pptx: null, pdf: null });
              setStatus("Idle");
              setError(null);
            }}
          >
            Logout
          </button>
        </div>
      </section>
    );
  }

  function renderCurrentPage() {
    switch (currentPage) {
      case "home":
        return renderHomePage();
      case "my-slides":
        return renderMySlidesPage();
      case "templates":
        return renderTemplateAdminPage();
      case "users":
        return renderUsersPage();
      case "llm-providers":
        return renderLlmProvidersPage();
      case "contact":
        return renderContactPage();
      case "account":
        return renderAccountPage();
      default:
        return renderHomePage();
    }
  }

  async function preview() {
    setError(null);
    setStatus("Generating preview...");

    if (!title.trim()) {
      setStatus("Failed");
      setError("Please enter a presentation title.");
      return;
    }

    if (contentType === "text" && text.trim().length < 50) {
      setStatus("Failed");
      setError("Please enter at least 50 characters of text.");
      return;
    }
    if (contentType === "file" && !contentFile) {
      setStatus("Failed");
      setError("Please upload a .docx or .pdf file.");
      return;
    }
    if (contentType === "prompt" && promptText.trim().length < 20) {
      setStatus("Failed");
      setError("Please enter a descriptive prompt.");
      return;
    }

    const formData = new FormData();
    formData.append('user_id', '1');
    formData.append('content_type', contentType);
    if (contentType === 'text') {
      formData.append('content_text', text);
    }
    if (contentType === 'prompt') {
      formData.append('prompt_text', promptText);
    }
    if (contentType === 'file' && contentFile) {
      formData.append('content_file', contentFile);
    }
    formData.append('title', title);
    formData.append('slide_count', slideCount.toString());
    formData.append('image_percent', imagePercent.toString());
    formData.append('theory_percent', theoryPercent.toString());
    formData.append('audience_level', audienceLevel);
    formData.append('palette_id', paletteId.toString());
    if (templateId) {
      formData.append('template_id', templateId.toString());
    }
    if (logoUrl) {
      formData.append('logo_url', logoUrl);
    }
    if (logoFile) {
      formData.append('logo_file', logoFile);
    }

    try {
      const response = await fetch(`${apiBase}/api/presentations/preview`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        setStatus("Failed");
        setError(errorData?.detail || errorData?.message || response.statusText || "Preview failed");
        return;
      }

      const data = await response.json();
      setPreviewSlides(data.slides);
      setStatus("Preview ready");
    } catch (err) {
      setStatus("Error");
      setError(err instanceof Error ? err.message : "Network error");
    }
  }

  async function generate() {
    setError(null);
    setStatus("Generating presentation...");

    if (!title.trim()) {
      setStatus("Failed");
      setError("Please enter a presentation title.");
      return;
    }

    if (contentType === "text" && text.trim().length < 50) {
      setStatus("Failed");
      setError("Please enter at least 50 characters of text.");
      return;
    }
    if (contentType === "file" && !contentFile) {
      setStatus("Failed");
      setError("Please upload a .docx or .pdf file.");
      return;
    }
    if (contentType === "prompt" && promptText.trim().length < 20) {
      setStatus("Failed");
      setError("Please enter a descriptive prompt.");
      return;
    }

    const formData = new FormData();
    formData.append('user_id', '1');
    formData.append('content_type', contentType);
    if (contentType === 'text') {
      formData.append('content_text', text);
    }
    if (contentType === 'prompt') {
      formData.append('prompt_text', promptText);
    }
    if (contentType === 'file' && contentFile) {
      formData.append('content_file', contentFile);
    }
    formData.append('title', title);
    formData.append('slide_count', slideCount.toString());
    formData.append('image_percent', imagePercent.toString());
    formData.append('theory_percent', theoryPercent.toString());
    formData.append('audience_level', audienceLevel);
    formData.append('palette_id', paletteId.toString());
    if (templateId) {
      formData.append('template_id', templateId.toString());
    }
    if (logoUrl) {
      formData.append('logo_url', logoUrl);
    }
    if (logoFile) {
      formData.append('logo_file', logoFile);
    }

    try {
      const response = await fetch(`${apiBase}/api/presentations/generate`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => null);
        setStatus("Failed");
        setError(errorData?.detail || errorData?.message || response.statusText || "Generation failed");
        return;
      }

      const data = await response.json();
      setPresentationId(data.presentation_id);
      setDownloadLinks({
        pptx: data.pptx_url ? `${apiBase}${data.pptx_url}` : null,
        pdf: data.pdf_url ? `${apiBase}${data.pdf_url}` : null,
      });
      setStatus("Completed");

      if (!previewSlides.length) {
        await preview();
      }
    } catch (err) {
      setStatus("Error");
      setError(err instanceof Error ? err.message : "Network error");
    }
  }

  return (
    <div className={`app-container ${themeDark ? "dark" : ""}`}>
      <aside className="sidebar">
        <h2>SlideMaka</h2>
        <nav>
          <button onClick={() => setCurrentPage("home")} className={currentPage === "home" ? "active" : ""}>
            Home
          </button>
          <button onClick={() => { setCurrentPage("my-slides"); loadUserSlides(); }} className={currentPage === "my-slides" ? "active" : ""}>
            My Slides
          </button>
          {isAdmin && (
            <button onClick={() => setCurrentPage("templates")} className={currentPage === "templates" ? "active" : ""}>
              Templates
            </button>
          )}
          {hasAdminRights && (
            <button onClick={() => { setCurrentPage("llm-providers"); loadLlmProviders(); }} className={currentPage === "llm-providers" ? "active" : ""}>
              LLM Providers
            </button>
          )}
          {hasAdminRights && (
            <button onClick={() => { setCurrentPage("users"); loadUsers(); }} className={currentPage === "users" ? "active" : ""}>
              User Management
            </button>
          )}
          <button onClick={() => setCurrentPage("contact")} className={currentPage === "contact" ? "active" : ""}>
            Contact Us
          </button>
          <button onClick={() => setCurrentPage("account")} className={currentPage === "account" ? "active" : ""}>
            Account
          </button>
        </nav>
      </aside>
      <main className="main-content">
        <div className="topbar">
          <h1>SlideMaka Generator</h1>
          <button
            className={`theme-toggle ${themeDark ? "dark" : ""}`}
            onClick={() => setThemeDark((v) => !v)}
            title="Toggle light / dark mode"
          >
            {themeDark ? "☀️ Light" : "🌙 Dark"}
          </button>
        </div>
        {renderCurrentPage()}
      </main>
    </div>
  );
}
