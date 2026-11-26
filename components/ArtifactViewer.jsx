import React, { useState, useEffect, useRef } from 'react';
import { X, Download, Copy, FileCode, FileText, Presentation, Check, FolderPlus } from 'lucide-react';

/* ---------- URL helpers ---------- */
const ABSOLUTE_RE = /^https?:\/\//i;
const isAbsolute = (u) => !!u && ABSOLUTE_RE.test(u);

function normalizeDownloadParam(u) {
  try {
    const url = new URL(u);
    if (url.searchParams.has('download')) {
      const v = (url.searchParams.get('download') || '').trim().toLowerCase();
      // Strip ONLY if it's empty/boolean-ish. Keep when it's a filename.
      if (v === '' || v === 'true' || v === '1') {
        url.searchParams.delete('download');
      }
    }
    return url.toString();
  } catch {
    return u;
  }
}

function buildAbsoluteUrl(rawPath, opts) {
  const base = ((opts && opts.base) || process.env.NEXT_PUBLIC_API_URL || '').replace(/\/$/, '');
  const u = isAbsolute(rawPath)
    ? new URL(rawPath)
    : new URL(rawPath.replace(/^\//, '/'), base + '/');
  // Preserve filename download, strip only boolean/empty
  return normalizeDownloadParam(u.toString());
}

/* ---------- Markdown rendering with artifact markers ---------- */
const renderMarkdown = (text, artifacts = [], setSelectedArtifact) => {
  if (!text) return null;

  // Artifact marker: [ARTIFACT:<id>:<type>:<title>]
  const artifactPattern = /\[ARTIFACT:([^:]+):([^:]+):([^\]]+)\]/g;
  const parts = text.split(artifactPattern);

  if (parts.length > 1) {
    const elements = [];
    for (let i = 0; i < parts.length; i++) {
      if (i % 4 === 0) {
        if (parts[i]) {
          elements.push(
            <span key={`text-${i}`}>
              {renderMarkdownContent(parts[i])}
            </span>
          );
        }
      } else if (i % 4 === 1) {
        const artifactId = parts[i];
        const artifactType = (parts[i + 1] || '').toLowerCase();
        const artifactTitle = parts[i + 2];
        const artifact = artifacts.find(a => a.id === artifactId);

        if (artifact) {
          elements.push(
            <div
              key={`artifact-${artifactId}`}
              className="artifact-card bg-white border border-gray-200 p-4 rounded-lg cursor-pointer hover:border-blue-400 hover:shadow-md transition-all my-3"
              onClick={() => setSelectedArtifact(artifact)}
            >
              <div className="flex items-center gap-3">
                <FileText size={24} className="text-blue-500 flex-shrink-0" />
                <div className="flex-1">
                  <h4 className="font-semibold text-gray-800">{artifactTitle}</h4>
                  <p className="text-sm text-gray-600">
                    {artifactType === 'code'
                      ? 'View code'
                      : artifactType === 'presentation'
                      ? 'View presentation'
                      : 'View document'}
                  </p>
                </div>
              </div>
            </div>
          );
        }
        i += 2; // skip type + title
      }
    }
    return <>{elements}</>;
  }

  return renderMarkdownContent(text);
};

const renderMarkdownContent = (text) => {
  if (!text) return null;

  const processInline = (str) => {
    const parts = [];
    let remaining = str;
    let key = 0;

    while (remaining) {
      // order matters: links before italics/bold etc.
      const candidates = [
        { match: remaining.match(/\[([^\]]+)\]\(([^)]+)\)/), type: 'mdlink' },
        { match: remaining.match(/https?:\/\/[^\s<]+/), type: 'url' },
        { match: remaining.match(/\*\*(.+?)\*\*/), type: 'bold' },
        { match: remaining.match(/\*(.+?)\*/), type: 'italic' },
        { match: remaining.match(/~~(.+?)~~/), type: 'strikethrough' },
        { match: remaining.match(/`([^`]+)`/), type: 'code' },
      ].filter(m => m.match);

      if (candidates.length === 0) {
        parts.push(remaining);
        break;
      }

      let earliest = candidates[0];
      for (const c of candidates) {
        if (c.match.index < earliest.match.index) earliest = c;
      }

      if (earliest.match.index > 0) {
        parts.push(remaining.substring(0, earliest.match.index));
      }

      switch (earliest.type) {
        case 'bold':
          parts.push(<strong key={key++}>{earliest.match[1]}</strong>);
          break;
        case 'italic':
          parts.push(<em key={key++}>{earliest.match[1]}</em>);
          break;
        case 'strikethrough':
          parts.push(<del key={key++}>{earliest.match[1]}</del>);
          break;
        case 'code':
          parts.push(
            <code
              key={key++}
              style={{
                backgroundColor: '#f0f0f0',
                padding: '0.2em 0.4em',
                borderRadius: '3px',
                fontFamily: 'monospace',
                fontSize: '0.9em',
              }}
            >
              {earliest.match[1]}
            </code>
          );
          break;
        case 'mdlink': {
          const linkText = earliest.match[1];
          const linkUrl = earliest.match[2];
          parts.push(
            <a
              key={key++}
              href={linkUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#2563eb', textDecoration: 'underline', cursor: 'pointer' }}
              onMouseEnter={(e) => (e.target.style.color = '#1d4ed8')}
              onMouseLeave={(e) => (e.target.style.color = '#2563eb')}
            >
              {linkText}
            </a>
          );
          break;
        }
        case 'url': {
          const url = earliest.match[0];
          parts.push(
            <a
              key={key++}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ color: '#2563eb', textDecoration: 'underline', cursor: 'pointer' }}
              onMouseEnter={(e) => (e.target.style.color = '#1d4ed8')}
              onMouseLeave={(e) => (e.target.style.color = '#2563eb')}
            >
              {url}
            </a>
          );
          break;
        }
        default:
          break;
      }

      remaining = remaining.substring(earliest.match.index + earliest.match[0].length);
    }

    return parts;
  };

  const lines = text.split('\n');
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const processedLine = line;

    if (!line.trim()) {
      elements.push(<div key={i} style={{ height: '1em' }}>{'\u00A0'}</div>);
      i++;
      continue;
    }

    // tables
    if (line.includes('|') && i > 0 && i < lines.length - 1) {
      const prev = lines[i - 1];
      const next = lines[i + 1];
      if (prev.includes('|') && next.match(/^[\s\-|]+$/)) {
        const tableLines = [prev];
        let j = i + 1; // skip separator line
        while (j < lines.length && lines[j].includes('|')) {
          tableLines.push(lines[j]);
          j++;
        }
        const rows = tableLines.map(r =>
          r.split('|').map(c => c.trim()).filter(c => c !== '')
        );

        elements.push(
          <table key={`table-${i}`} style={{ borderCollapse: 'collapse', margin: '1em 0' }}>
            <thead>
              <tr>
                {rows[0].map((cell, idx) => (
                  <th
                    key={idx}
                    style={{
                      border: '1px solid #e5e7eb',
                      padding: '0.5em',
                      backgroundColor: 'var(--tw-prose-th-bgc, #f9fafb)',
                      textAlign: 'left',
                    }}
                  >
                    {processInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(1).map((row, ridx) => (
                <tr key={ridx}>
                  {row.map((cell, cidx) => (
                    <td key={cidx} style={{ border: '1px solid #e5e7eb', padding: '0.5em' }}>
                      {processInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        );
        i = j;
        continue;
      }
    }

    // hr
    if (line.trim().match(/^(---|___|\*\*\*)$/)) {
      elements.push(<hr key={i} style={{ border: 'none', borderTop: '1px solid #e5e7eb', margin: '1.5em 0' }} />);
      i++;
      continue;
    }

    // headers
    const headerMatch = line.match(/^(\s*)(#{1,6})\s+(.+)$/);
    if (headerMatch) {
      const hashes = headerMatch[2];
      const content = headerMatch[3];
      const level = hashes.length;
      const HeaderTag = `h${level}`;
      elements.push(
        <HeaderTag
          key={i}
          style={{
            fontWeight: 'bold',
            fontSize: level === 1 ? '2em' : level === 2 ? '1.5em' : level === 3 ? '1.17em' : '1em',
            margin: '1em 0 0.5em 0',
          }}
        >
          {processInline(content)}
        </HeaderTag>
      );
      i++;
      continue;
    }

    // code blocks
    if (line.trim().startsWith('```')) {
      const codeLines = [];
      i++;
      while (i < lines.length && !lines[i].trim().startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // skip closing ```
      elements.push(
        <pre
          key={`code-${i}`}
          style={{
            backgroundColor: '#f5f5f5',
            padding: '1em',
            borderRadius: '4px',
            margin: '1em 0',
            overflowX: 'auto',
            whiteSpace: 'pre',
            fontFamily: 'monospace',
          }}
        >
          <code>{codeLines.join('\n')}</code>
        </pre>
      );
      continue;
    }

    // blockquotes
    const quoteMatch = line.match(/^\s*>\s+(.+)$/);
    if (quoteMatch) {
      elements.push(
        <blockquote
          key={i}
          style={{
            borderLeft: '4px solid #e5e7eb',
            paddingLeft: '1em',
            fontStyle: 'italic',
            color: '#666',
            margin: '1em 0',
          }}
        >
          {processInline(quoteMatch[1])}
        </blockquote>
      );
      i++;
      continue;
    }

    // unordered list
    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (listMatch) {
      elements.push(
        <div key={i} style={{ marginLeft: '2em', marginBottom: '0.5em' }}>
          • {processInline(listMatch[1])}
        </div>
      );
      i++;
      continue;
    }

    // ordered list (render simply)
    const numberedMatch = line.match(/^\s*(\d+)\.\s+(.+)$/);
    if (numberedMatch) {
      elements.push(
        <div key={i} style={{ marginBottom: '1em' }}>
          <span>
            {processedLine.substring(
              0,
              processedLine.indexOf(numberedMatch[1]) + numberedMatch[1].length + 1
            )}
          </span>{' '}
          {processInline(numberedMatch[2])}
        </div>
      );
      i++;
      continue;
    }

    // paragraph
    const paragraphLines = [processedLine];
    i++;
    while (i < lines.length) {
      const nextLine = lines[i];
      if (
        !nextLine.trim() ||
        nextLine.match(/^\s*(#{1,6})\s+/) ||
        nextLine.match(/^\s*[-*]\s+/) ||
        nextLine.match(/^\s*(\d+)\.\s+/) ||
        nextLine.match(/^\s*>\s+/) ||
        nextLine.trim().startsWith('```') ||
        nextLine.trim().match(/^(---|___|\*\*\*)$/)
      ) {
        break;
      }
      paragraphLines.push(nextLine);
      i++;
    }

    elements.push(
      <div key={`p-${i}`} style={{ marginBottom: '1em' }}>
        {paragraphLines.map((pLine, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <br />}
            {processInline(pLine)}
          </React.Fragment>
        ))}
      </div>
    );
  }

  return <div style={{ whiteSpace: 'pre-wrap', wordWrap: 'break-word' }}>{elements}</div>;
};

/* ---------- PDF Viewer (uses NEXT_PUBLIC_API_URL) ---------- */
const PDFViewer = ({
  pdfPath,
  baseUrl = process.env.NEXT_PUBLIC_API_URL || '',
}) => {
  const canvasRef = useRef(null);
  const [pageNum, setPageNum] = useState(1);
  const [numPages, setNumPages] = useState(null);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [pdfjsLib, setPdfjsLib] = useState(null);
  const url = isAbsolute(pdfPath)
    ? normalizeDownloadParam(pdfPath)
    : buildAbsoluteUrl(pdfPath, { base: baseUrl });

  useEffect(() => {
    const loadPdfJs = async () => {
      const pdfjs = await import('pdfjs-dist');
      pdfjs.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/${pdfjs.version}/pdf.worker.min.js`;
      setPdfjsLib(pdfjs);
    };
    loadPdfJs();
  }, []);

  useEffect(() => {
    if (!pdfjsLib) return;

    const loadPdf = async () => {
      try {
        const loadingTask = pdfjsLib.getDocument(url);
        const pdf = await loadingTask.promise;
        setPdfDoc(pdf);
        setNumPages(pdf.numPages);
        renderPage(1, pdf);
      } catch (error) {
        console.error('Error loading PDF:', error);
      }
    };

    loadPdf();
  }, [url, pdfjsLib]);

  const renderPage = async (pageNumber, pdf = pdfDoc) => {
    if (!pdf) return;
    const page = await pdf.getPage(pageNumber);
    const canvas = canvasRef.current;
    const context = canvas.getContext('2d');
    const viewport = page.getViewport({ scale: 1.5 });

    canvas.height = viewport.height;
    canvas.width = viewport.width;

    await page.render({ canvasContext: context, viewport }).promise;
  };

  const goToPrevPage = () => {
    if (pageNum <= 1) return;
    const newPage = pageNum - 1;
    setPageNum(newPage);
    renderPage(newPage);
  };

  const goToNextPage = () => {
    if (pageNum >= numPages) return;
    const newPage = pageNum + 1;
    setPageNum(newPage);
    renderPage(newPage);
  };

  return (
    <div className="pdf-viewer flex flex-col h-full">
      <div className="pdf-controls bg-gray-100 p-2 flex justify-center items-center gap-4">
        <button onClick={goToPrevPage} disabled={pageNum <= 1} className="px-3 py-1 bg-white rounded disabled:opacity-50">
          Previous
        </button>
        <span>Page {pageNum} of {numPages || '?'}</span>
        <button onClick={goToNextPage} disabled={pageNum >= numPages} className="px-3 py-1 bg-white rounded disabled:opacity-50">
          Next
        </button>
      </div>
      <div className="pdf-canvas-container flex-1 overflow-auto flex justify-center p-4 bg-gray-50">
        <canvas ref={canvasRef} className="shadow-lg" />
      </div>
    </div>
  );
};

/* ---------- Artifact Viewer (uses NEXT_PUBLIC_API_URL everywhere) ---------- */
const ArtifactViewer = ({ artifact, onClose, projectId }) => {
  const [copied, setCopied] = useState(false);
  const [savedToProject, setSavedToProject] = useState(false);

  const isPreviewOnly = artifact?.type === 'document_preview';

  const handleCopy = async () => {
    try {
      if (isPreviewOnly) return;
      await navigator.clipboard.writeText(artifact.content || '');
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  };

  const handleDownload = async () => {
    try {
      if (isPreviewOnly) return;

      // Prefer a direct absolute URL (signed/public) if present
      const direct =
        artifact?.download_url ||
        artifact?.public_url ||
        artifact?.url ||
        artifact?.href ||
        artifact?.path;

      if (direct) {
        const absolute = isAbsolute(direct)
          ? direct
          : buildAbsoluteUrl(direct, { base: process.env.NEXT_PUBLIC_API_URL });
        window.open(normalizeDownloadParam(absolute), '_blank', 'noopener,noreferrer');
        return;
      }

      // Otherwise, ask our API to resolve it (keeps old behavior)
      const res = await fetch(`/api/artifacts/download/${artifact.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artifact }),
      });
      if (!res.ok) throw new Error('Download request failed');
      const data = await res.json();
      const rawUrl = data?.download_url;
      if (!rawUrl) throw new Error('No download_url in response');

      // Build absolute URL and keep filename download param if provided
      const finalUrl = buildAbsoluteUrl(rawUrl, { base: process.env.NEXT_PUBLIC_API_URL });
      window.open(finalUrl, '_blank', 'noopener,noreferrer');
    } catch (err) {
      console.error('Download error:', err);
      alert('Failed to download artifact');
    }
  };

  const handleSaveToProject = async () => {
    try {
      if (isPreviewOnly) return;

      const response = await fetch('/api/project/files/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          projectId,
          filename: `${artifact.title}.${artifact.language || 'txt'}`,
          content: artifact.content,
          artifactId: artifact.id,
        }),
      });

      if (response.ok) {
        setSavedToProject(true);
        setTimeout(() => setSavedToProject(false), 2000);
      }
    } catch (error) {
      console.error('Save error:', error);
      alert('Failed to save to project');
    }
  };

  const getIcon = () => {
    switch (artifact.type) {
      case 'code':
        return <FileCode size={20} />;
      case 'markdown':
        return <FileText size={20} />;
      case 'presentation':
        return <Presentation size={20} />;
      case 'document_preview':
        return <FileText size={20} />;
      default:
        return <FileText size={20} />;
    }
  };

  const renderContent = () => {
    // PDF previews generated server-side
    if (artifact.type === 'document_preview' && (artifact.preview_url || artifact.preview)) {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL || '';
      const pdfPath = artifact.preview_url || artifact.preview; // backward compatibility
      return <PDFViewer pdfPath={pdfPath} baseUrl={baseUrl} />;
    }

    switch (artifact.type) {
      case 'code':
        return (
          <div className="code-viewer">
            <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-auto h-full">
              <code>{artifact.content}</code>
            </pre>
          </div>
        );
      case 'markdown':
        return (
          <div className="markdown-viewer p-6 prose max-w-none">
            {renderMarkdownContent(artifact.content)}
          </div>
        );
      default:
        return <div className="artifact-plaintext p-4">{renderMarkdownContent(artifact.content)}</div>;
    }
  };

  return (
    <div className="artifact-viewer-panel h-full flex flex-col bg-gray-50">
      <div className="artifact-viewer-header bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {getIcon()}
          <div>
            <h3 className="font-semibold text-lg">{artifact.title}</h3>
            <span className="text-sm text-gray-500">
              {artifact.type === 'code' && artifact.language && `${artifact.language} • `}
              {artifact.type === 'document_preview' && artifact.document_type && `${artifact.document_type} • PDF Preview`}
              {artifact.metadata?.lines && `${artifact.metadata.lines} lines`}
              {artifact.metadata?.slideCount && `${artifact.metadata.slideCount} slides`}
            </span>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Optional quick open for Supabase files */}
          {isAbsolute(artifact?.path) && (
            <a
              href={normalizeDownloadParam(artifact.path)}
              target="_blank"
              rel="noopener noreferrer"
              className="artifact-action-btn flex items-center gap-2 px-3 py-1.5 text-sm"
              title="Open in new tab"
            >
              Open
            </a>
          )}

          <button
            onClick={handleCopy}
            className="artifact-action-btn flex items-center gap-2 px-3 py-1.5 text-sm"
            disabled={isPreviewOnly}
            title={isPreviewOnly ? 'Copy disabled for previews' : 'Copy to clipboard'}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
            {copied ? 'Copied!' : 'Copy'}
          </button>

          {projectId && (
            <button
              onClick={handleSaveToProject}
              className="artifact-action-btn flex items-center gap-2 px-3 py-1.5 text-sm"
              disabled={isPreviewOnly}
              title={isPreviewOnly ? 'Save disabled for previews' : 'Save to project'}
            >
              {savedToProject ? <Check size={16} /> : <FolderPlus size={16} />}
              {savedToProject ? 'Saved!' : 'Save to Project'}
            </button>
          )}

          <button
            onClick={handleDownload}
            className="artifact-action-btn flex items-center gap-2 px-3 py-1.5 text-sm"
            disabled={isPreviewOnly}
            title={isPreviewOnly ? 'Download disabled for previews' : 'Download file'}
          >
            <Download size={16} />
            Download
          </button>

          <button
            onClick={onClose}
            className="ml-2 p-1.5 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded"
            title="Close"
          >
            <X size={20} />
          </button>
        </div>
      </div>

      <div className="artifact-viewer-content flex-1 overflow-auto">
        {renderContent()}
      </div>
    </div>
  );
};

export default ArtifactViewer;
