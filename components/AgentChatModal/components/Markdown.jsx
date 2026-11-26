import { FileText } from "lucide-react";
import MarkdownContent from "./MarkdownContent";

const Markdown = ({ text, artifacts = [], setSelectedArtifact }) => {
  if (!text) return null;

  // First check for artifact markers before processing other markdown
  const artifactPattern = /\[ARTIFACT:([^:]+):([^:]+):([^\]]+)\]/g;

  // Split text by artifact markers
  const parts = text.split(artifactPattern);

  if (parts.length > 1) {
    // We have artifacts to process
    const elements = [];

    for (let i = 0; i < parts.length; i++) {
      if (i % 4 === 0) {
        // Regular text part - process with existing markdown logic
        if (parts[i]) {
          elements.push(
            <span key={`text-${i}`}>
              <MarkdownContent text={parts[i]} />
            </span>
          );
        }
      } else if (i % 4 === 1) {
        // This is the artifact ID
        const artifactId = parts[i];
        const artifactType = parts[i + 1];
        const artifactTitle = parts[i + 2];

        // Find the artifact in the artifacts array
        const artifact = artifacts.find((a) => a.id === artifactId);

        if (artifact) {
          elements.push(
            <div
              key={`artifact-${artifactId}`}
              className="p-4 my-3 transition-all bg-white border border-gray-200 rounded-lg cursor-pointer artifact-card hover:border-blue-400 hover:shadow-md"
              onClick={() => setSelectedArtifact(artifact)}
            >
              <div className="flex items-center gap-3">
                <FileText size={24} className="flex-shrink-0 text-blue-500" />
                <div className="flex-1">
                  <h4 className="font-semibold text-gray-800">
                    {artifactTitle}
                  </h4>
                  <p className="text-sm text-gray-600">
                    {artifactType === "CODE"
                      ? "View code"
                      : artifactType === "PRESENTATION"
                      ? "View presentation"
                      : "View document"}
                  </p>
                </div>
              </div>
            </div>
          );
        }

        // Skip the next two parts as we've already used them
        i += 2;
      }
    }

    return <>{elements}</>;
  }

  return <MarkdownContent text={text} />;
};

export default Markdown;
