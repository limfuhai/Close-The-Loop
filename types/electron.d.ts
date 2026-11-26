// electron.d.ts
interface Window {
    fileSystem: {
      saveFile: (file: File) => Promise<string | { id: string, path: string }>;
      deleteFile: (filePath: string) => Promise<boolean>;
      // Add other fileSystem methods as needed
    };
    electron?: {
      send: (channel: string, data: any) => void;
      receive: (channel: string, func: Function) => void;
      // Add other electron methods as needed
    };
  }