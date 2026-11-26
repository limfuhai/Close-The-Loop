import React, { useEffect, useRef } from "react";

import Prism from "prismjs";
import "prismjs/components/prism-bash";
import "prismjs/components/prism-css";
import "prismjs/components/prism-java";
import "prismjs/components/prism-javascript";
import "prismjs/components/prism-json";
import "prismjs/components/prism-jsx";
import "prismjs/components/prism-markdown";
import "prismjs/components/prism-python";
import "prismjs/components/prism-sql";
import "prismjs/components/prism-tsx";
import "prismjs/components/prism-typescript";
import "prismjs/themes/prism-tomorrow.css";

const MarkdownContent = ({ text }) => {
  const contentRef = useRef(null);

  useEffect(() => {
    if (contentRef.current) {
      Prism.highlightAllUnder(contentRef.current);
    }
  }, [text]);

  if (!text) return null;

  // Language mapping for common aliases
  const getLanguageClass = (lang) => {
    if (!lang) return "language-plaintext";

    const langMap = {
      js: "javascript",
      ts: "typescript",
      py: "python",
      sh: "bash",
      shell: "bash",
      yml: "yaml",
      md: "markdown",
    };

    const normalized = lang.toLowerCase().trim();
    return `language-${langMap[normalized] || normalized}`;
  };

  // Process inline formatting
  const processInline = (str) => {
    const parts = [];
    let remaining = str;
    let key = 0;

    while (remaining) {
      // Find next formatting - IMPORTANT: Check links BEFORE italics to avoid conflicts
      const matches = [
        { match: remaining.match(/\[([^\]]+)\]\(([^)]+)\)/), type: "mdlink" },
        { match: remaining.match(/https?:\/\/[^\s<]+/), type: "url" },
        { match: remaining.match(/\*\*(.+?)\*\*/), type: "bold" },
        { match: remaining.match(/\*(.+?)\*/), type: "italic" },
        { match: remaining.match(/~~(.+?)~~/), type: "strikethrough" },
        { match: remaining.match(/`([^`]+)`/), type: "code" },
      ].filter((m) => m.match);

      if (matches.length === 0) {
        parts.push(remaining);
        break;
      }

      // Find the earliest match
      let earliest = matches[0];
      for (const m of matches) {
        if (m.match.index < earliest.match.index) {
          earliest = m;
        }
      }

      // Add text before match
      if (earliest.match.index > 0) {
        parts.push(remaining.substring(0, earliest.match.index));
      }

      // Add formatted content
      switch (earliest.type) {
        case "bold":
          parts.push(<strong key={key++}>{earliest.match[1]}</strong>);
          break;
        case "italic":
          parts.push(<em key={key++}>{earliest.match[1]}</em>);
          break;
        case "strikethrough":
          parts.push(<del key={key++}>{earliest.match[1]}</del>);
          break;
        case "code":
          parts.push(
            <code
              key={key++}
              style={{
                backgroundColor: "#f0f0f0",
                padding: "0.2em 0.4em",
                borderRadius: "3px",
                fontFamily: "monospace",
                fontSize: "0.9em",
              }}
            >
              {earliest.match[1]}
            </code>
          );
          break;
        case "mdlink":
          // Markdown link: [text](url)
          const linkText = earliest.match[1];
          const linkUrl = earliest.match[2];
          parts.push(
            <a
              key={key++}
              href={linkUrl}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: "#2563eb",
                textDecoration: "underline",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => (e.target.style.color = "#1d4ed8")}
              onMouseLeave={(e) => (e.target.style.color = "#2563eb")}
            >
              {linkText}
            </a>
          );
          break;
        case "url":
          // Plain URL
          const url = earliest.match[0];
          parts.push(
            <a
              key={key++}
              href={url}
              target="_blank"
              rel="noopener noreferrer"
              style={{
                color: "#2563eb",
                textDecoration: "underline",
                cursor: "pointer",
              }}
              onMouseEnter={(e) => (e.target.style.color = "#1d4ed8")}
              onMouseLeave={(e) => (e.target.style.color = "#2563eb")}
            >
              {url}
            </a>
          );
          break;
      }

      // Update remaining
      remaining = remaining.substring(
        earliest.match.index + earliest.match[0].length
      );
    }

    return parts;
  };

  // Split into lines but preserve empty lines
  const lines = text.split("\n");
  const elements = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Preserve leading spaces
    const leadingSpaces = line.match(/^(\s+)/)?.[1]?.length || 0;
    const processedLine = line;

    // Empty line = paragraph break
    if (!line.trim()) {
      elements.push(
        <div key={i} style={{ height: "1em" }}>
          {"\u00A0"}
        </div>
      );
      i++;
      continue;
    }

    // Tables (skip if inside code block)
    if (line.includes("|") && i > 0 && i < lines.length - 1) {
      const prevLine = lines[i - 1];
      const nextLine = lines[i + 1];

      if (prevLine.includes("|") && nextLine.match(/^[\s\-|]+$/)) {
        // This is a table
        const tableLines = [prevLine];
        let j = i;

        // Skip header separator
        j++;

        // Collect table rows
        while (j < lines.length && lines[j].includes("|")) {
          tableLines.push(lines[j]);
          j++;
        }

        // Parse table
        const rows = tableLines.map((row) =>
          row
            .split("|")
            .map((cell) => cell.trim())
            .filter((cell) => cell !== "")
        );

        elements.push(
          <table
            key={`table-${i}`}
            style={{
              borderCollapse: "collapse",
              margin: "1em 0",
            }}
          >
            <thead>
              <tr>
                {rows[0].map((cell, idx) => (
                  <th
                    key={idx}
                    style={{
                      border: "1px solid #e5e7eb",
                      padding: "0.5em",
                      backgroundColor: "#f9fafb",
                      textAlign: "left",
                    }}
                  >
                    {processInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(1).map((row, rowIdx) => (
                <tr key={rowIdx}>
                  {row.map((cell, cellIdx) => (
                    <td
                      key={cellIdx}
                      style={{
                        border: "1px solid #e5e7eb",
                        padding: "0.5em",
                      }}
                    >
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

    // Horizontal rules
    if (line.trim().match(/^(---|___|\*\*\*)$/)) {
      elements.push(
        <hr
          key={i}
          style={{
            border: "none",
            borderTop: "1px solid #e5e7eb",
            margin: "1.5em 0",
          }}
        />
      );
      i++;
      continue;
    }

    // Headers
    const headerMatch = line.match(/^(\s*)(#{1,6})\s+(.+)$/);
    if (headerMatch) {
      const [, spaces, hashes, content] = headerMatch;
      const level = hashes.length;
      const HeaderTag = `h${level}`;

      elements.push(
        <HeaderTag
          key={i}
          style={{
            fontWeight: "bold",
            fontSize:
              level === 1
                ? "2em"
                : level === 2
                ? "1.5em"
                : level === 3
                ? "1.17em"
                : "1em",
            margin: "1em 0 0.5em 0",
          }}
        >
          {processInline(content)}
        </HeaderTag>
      );
      i++;
      continue;
    }

    // Code blocks with syntax highlighting
    if (line.trim().startsWith("```")) {
      const langMatch = line.trim().match(/^```(\w+)?/);
      const language = langMatch?.[1] || "";
      const languageClass = getLanguageClass(language);

      const codeLines = [];
      i++; // Skip the opening ```
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // Skip the closing ```

      const codeContent = codeLines.join("\n");

      elements.push(
        <div
          key={`code-${i}`}
          style={{ position: "relative", margin: "1em 0" }}
        >
          {language && (
            <div
              style={{
                position: "absolute",
                top: "0.5em",
                right: "0.5em",
                fontSize: "0.75em",
                color: "#999",
                textTransform: "uppercase",
                fontFamily: "monospace",
                background: "rgba(0,0,0,0.1)",
                padding: "0.2em 0.5em",
                borderRadius: "3px",
              }}
            >
              {language}
            </div>
          )}
          <pre
            style={{
              margin: 0,
              borderRadius: "4px",
              overflow: "auto",
            }}
          >
            <code className={languageClass}>{codeContent}</code>
          </pre>
        </div>
      );
      continue;
    }

    // Blockquotes
    const quoteMatch = line.match(/^\s*>\s+(.+)$/);
    if (quoteMatch) {
      elements.push(
        <blockquote
          key={i}
          style={{
            borderLeft: "4px solid #e5e7eb",
            paddingLeft: "1em",
            fontStyle: "italic",
            color: "#666",
            margin: "1em 0",
          }}
        >
          {processInline(quoteMatch[1])}
        </blockquote>
      );
      i++;
      continue;
    }

    // Lists
    const listMatch = line.match(/^\s*[-*]\s+(.+)$/);
    if (listMatch) {
      elements.push(
        <div key={i} style={{ marginLeft: "2em", marginBottom: "0.5em" }}>
          • {processInline(listMatch[1])}
        </div>
      );
      i++;
      continue;
    }

    // Numbered lists - treat as separate paragraphs
    const numberedMatch = line.match(/^\s*(\d+)\.\s+(.+)$/);
    if (numberedMatch) {
      elements.push(
        <div key={i} style={{ marginBottom: "1em" }}>
          <span style={{ marginLeft: leadingSpaces ? "0" : "0" }}>
            {processedLine.substring(
              0,
              processedLine.indexOf(numberedMatch[1]) +
                numberedMatch[1].length +
                1
            )}
          </span>
          {processInline(numberedMatch[2])}
        </div>
      );
      i++;
      continue;
    }

    // Regular text - check if it's part of a paragraph
    const paragraphLines = [processedLine];
    i++;

    // Collect lines until we hit a blank line or special format
    while (i < lines.length) {
      const nextLine = lines[i];

      // Stop if blank line or special format
      if (
        !nextLine.trim() ||
        nextLine.match(/^\s*(#{1,6})\s+/) ||
        nextLine.match(/^\s*[-*]\s+/) ||
        nextLine.match(/^\s*(\d+)\.\s+/) ||
        nextLine.match(/^\s*>\s+/) ||
        nextLine.trim().startsWith("```") ||
        nextLine.trim().match(/^(---|___|\*\*\*)$/)
      ) {
        break;
      }

      // Add line with preserved spaces
      let processed = nextLine;
      const spaces = nextLine.match(/^(\s+)/);
      if (spaces) {
        processed =
          "\u00A0".repeat(spaces[1].length) +
          nextLine.substring(spaces[1].length);
      }
      paragraphLines.push(processed);
      i++;
    }

    // Render paragraph
    elements.push(
      <div key={`p-${i}`} style={{ marginBottom: "1em" }}>
        {paragraphLines.map((pLine, idx) => (
          <React.Fragment key={idx}>
            {idx > 0 && <br />}
            {processInline(pLine)}
          </React.Fragment>
        ))}
      </div>
    );
  }

  return (
    <div
      ref={contentRef}
      style={{ whiteSpace: "pre-wrap", wordWrap: "break-word" }}
    >
      {elements}
    </div>
  );
};

export default MarkdownContent;
