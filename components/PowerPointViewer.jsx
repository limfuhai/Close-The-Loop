import React, { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

const PowerPointViewer = ({ slides }) => {
  const [currentSlide, setCurrentSlide] = useState(0);
  
  const goToPrevious = () => {
    setCurrentSlide(Math.max(0, currentSlide - 1));
  };
  
  const goToNext = () => {
    setCurrentSlide(Math.min(slides.length - 1, currentSlide + 1));
  };
  
  if (!slides || slides.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-500">
        No slides available
      </div>
    );
  }
  
  const currentSlideData = slides[currentSlide];
  
  return (
    <div className="powerpoint-viewer h-full flex flex-col bg-gray-100">
      {/* Main slide area */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="slide-container bg-white rounded-lg shadow-lg w-full max-w-4xl aspect-video p-12">
          <div className="h-full flex flex-col">
            <h2 className="text-3xl font-bold mb-6 text-gray-800">
              {currentSlideData.title}
            </h2>
            <div className="slide-content flex-1 overflow-auto">
              {currentSlideData.content.split('\n').map((line, idx) => {
                // Handle bullet points
                if (line.trim().startsWith('•') || line.trim().startsWith('-')) {
                  return (
                    <p key={idx} className="mb-3 ml-4 text-lg">
                      {line}
                    </p>
                  );
                }
                // Handle empty lines
                if (!line.trim()) {
                  return <br key={idx} />;
                }
                // Regular paragraphs
                return (
                  <p key={idx} className="mb-3 text-lg">
                    {line}
                  </p>
                );
              })}
            </div>
          </div>
        </div>
      </div>
      
      {/* Controls */}
      <div className="bg-white border-t border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <button
            onClick={goToPrevious}
            disabled={currentSlide === 0}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            <ChevronLeft size={20} />
            Previous
          </button>
          
          <span className="text-gray-600 font-medium">
            Slide {currentSlide + 1} of {slides.length}
          </span>
          
          <button
            onClick={goToNext}
            disabled={currentSlide === slides.length - 1}
            className="flex items-center gap-2 px-4 py-2 bg-gray-100 hover:bg-gray-200 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Next
            <ChevronRight size={20} />
          </button>
        </div>
        
        {/* Slide thumbnails */}
        <div className="mt-4 flex gap-2 overflow-x-auto pb-2">
          {slides.map((slide, idx) => (
            <button
              key={idx}
              onClick={() => setCurrentSlide(idx)}
              className={`min-w-[120px] p-3 rounded border-2 transition-all ${
                idx === currentSlide
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-gray-200 hover:border-gray-300 bg-white'
              }`}
            >
              <div className="text-xs font-medium text-left">
                Slide {idx + 1}
              </div>
              <div className="text-xs text-gray-600 truncate mt-1">
                {slide.title}
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
};

export default PowerPointViewer;