import React, { useState } from 'react';
import { Table, BarChart } from 'lucide-react';

const SheetsViewer = ({ sections = [], chartData = [] }) => {
  const [activeTab, setActiveTab] = useState('data');
  
  if (!sections || sections.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        No spreadsheet data available
      </div>
    );
  }
  
  const renderTable = (section) => {
    if (!section.headers || !section.data) return null;
    
    return (
      <div key={section.name} className="mb-8">
        {section.name && (
          <h3 className="text-lg font-semibold mb-3">{section.name}</h3>
        )}
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse border border-gray-300">
            <thead>
              <tr className="bg-gray-100">
                {section.headers.map((header, idx) => (
                  <th key={idx} className="border border-gray-300 px-4 py-2 text-left font-semibold">
                    {header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {section.data.map((row, rowIdx) => (
                <tr key={rowIdx} className={rowIdx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}>
                  {row.map((cell, cellIdx) => (
                    <td key={cellIdx} className="border border-gray-300 px-4 py-2">
                      {cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  };
  
  const renderSimpleChart = (data) => {
    if (!data.headers || !data.data || data.data.length === 0) return null;
    
    // Find max value for scaling
    const numericData = data.data.map(row => 
      row.slice(1).map(val => parseFloat(val.toString().replace(/[^0-9.-]/g, '')) || 0)
    );
    const maxValue = Math.max(...numericData.flat());
    
    return (
      <div key={data.title} className="mb-8">
        <h3 className="text-lg font-semibold mb-3">{data.title}</h3>
        <div className="bg-white p-4 rounded-lg shadow">
          {/* Simple bar chart visualization */}
          <div className="space-y-4">
            {data.data.map((row, idx) => (
              <div key={idx} className="flex items-center gap-4">
                <div className="w-24 text-sm font-medium">{row[0]}</div>
                <div className="flex-1 flex gap-2 items-center">
                  {row.slice(1).map((value, vIdx) => {
                    const numValue = parseFloat(value.toString().replace(/[^0-9.-]/g, '')) || 0;
                    const percentage = (numValue / maxValue) * 100;
                    return (
                      <div key={vIdx} className="flex-1">
                        <div className="relative bg-gray-200 h-8 rounded">
                          <div 
                            className="absolute left-0 top-0 h-full bg-blue-500 rounded"
                            style={{ width: `${percentage}%` }}
                          />
                          <span className="absolute inset-0 flex items-center justify-center text-xs font-medium">
                            {value}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 flex gap-4 text-sm">
            {data.headers.slice(1).map((header, idx) => (
              <div key={idx} className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded ${idx === 0 ? 'bg-blue-500' : idx === 1 ? 'bg-green-500' : 'bg-purple-500'}`} />
                <span>{header}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  };
  
  return (
    <div className="sheets-viewer h-full flex flex-col bg-gray-50">
      {/* Tab navigation */}
      <div className="bg-white border-b border-gray-200 px-4">
        <div className="flex gap-4">
          <button
            onClick={() => setActiveTab('data')}
            className={`py-3 px-4 border-b-2 transition-colors ${
              activeTab === 'data' 
                ? 'border-blue-500 text-blue-600' 
                : 'border-transparent text-gray-600 hover:text-gray-800'
            }`}
          >
            <div className="flex items-center gap-2">
              <Table size={18} />
              <span>Data</span>
            </div>
          </button>
          {chartData && chartData.length > 0 && (
            <button
              onClick={() => setActiveTab('charts')}
              className={`py-3 px-4 border-b-2 transition-colors ${
                activeTab === 'charts' 
                  ? 'border-blue-500 text-blue-600' 
                  : 'border-transparent text-gray-600 hover:text-gray-800'
              }`}
            >
              <div className="flex items-center gap-2">
                <BarChart size={18} />
                <span>Charts</span>
              </div>
            </button>
          )}
        </div>
      </div>
      
      {/* Content area */}
      <div className="flex-1 overflow-auto p-6">
        {activeTab === 'data' ? (
          <div>
            {sections.map((section, idx) => renderTable(section))}
          </div>
        ) : (
          <div>
            {chartData.map((data, idx) => renderSimpleChart(data))}
          </div>
        )}
      </div>
    </div>
  );
};

export default SheetsViewer;