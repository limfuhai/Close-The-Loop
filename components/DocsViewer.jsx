import React from 'react';
import { FileText, Hash } from 'lucide-react';

const DocsViewer = ({ sections = [] }) => {
  if (!sections || sections.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        No document content available
      </div>
    );
  }
  
  const renderSection = (section, idx) => {
    switch (section.type) {
      case 'title':
        return (
          <h1 key={idx} className="text-3xl font-bold mb-6 text-gray-900">
            {section.text}
          </h1>
        );
        
      case 'subtitle':
        return (
          <p key={idx} className="text-lg text-gray-600 mb-6">
            {section.text}
          </p>
        );
        
      case 'heading1':
        return (
          <h2 key={idx} className="text-2xl font-bold mt-8 mb-4 text-gray-800 flex items-center gap-2">
            <Hash size={20} className="text-gray-400" />
            {section.text}
          </h2>
        );
        
      case 'heading2':
        return (
          <h3 key={idx} className="text-xl font-semibold mt-6 mb-3 text-gray-700 flex items-center gap-2">
            <Hash size={16} className="text-gray-400" />
            {section.text}
          </h3>
        );
        
      case 'paragraph':
        return (
          <p key={idx} className="mb-4 text-gray-700 leading-relaxed">
            {section.text}
          </p>
        );
        
      default:
        return (
          <div key={idx} className="mb-4 text-gray-700">
            {section.text}
          </div>
        );
    }
  };
  
  // Create a table of contents from headings
  const tableOfContents = sections
    .filter(section => section.type === 'heading1' || section.type === 'heading2')
    .map((section, idx) => ({
      text: section.text,
      level: section.type === 'heading1' ? 1 : 2,
      id: `heading-${idx}`
    }));
  
  return (
    <div className="docs-viewer h-full flex bg-gray-50">
      {/* Table of Contents Sidebar */}
      {tableOfContents.length > 0 && (
        <div className="w-64 bg-white border-r border-gray-200 p-4 overflow-y-auto">
          <h3 className="font-semibold text-gray-700 mb-4 flex items-center gap-2">
            <FileText size={18} />
            Table of Contents
          </h3>
          <nav className="space-y-2">
            {tableOfContents.map((item, idx) => (
              <a
                key={idx}
                href={`#${item.id}`}
                className={`block ${
                  item.level === 1 
                    ? 'text-sm font-medium text-gray-700 hover:text-blue-600' 
                    : 'text-sm text-gray-600 hover:text-blue-500 ml-4'
                }`}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(item.id)?.scrollIntoView({ behavior: 'smooth' });
                }}
              >
                {item.text}
              </a>
            ))}
          </nav>
        </div>
      )}
      
      {/* Document Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto p-8 bg-white shadow-sm">
          {sections.map((section, idx) => {
            // Add IDs to headings for navigation
            if (section.type === 'heading1' || section.type === 'heading2') {
              const headingIdx = tableOfContents.findIndex(
                toc => toc.text === section.text
              );
              return (
                <div key={idx} id={headingIdx >= 0 ? `heading-${headingIdx}` : undefined}>
                  {renderSection(section, idx)}
                </div>
              );
            }
            return renderSection(section, idx);
          })}
          
          {/* Document footer */}
          <div className="mt-12 pt-8 border-t border-gray-200 text-center text-sm text-gray-500">
            End of document
          </div>
        </div>
      </div>
    </div>
  );
};

export default DocsViewer;