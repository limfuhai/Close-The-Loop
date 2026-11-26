import { useRouter } from 'next/router';
import { useEffect } from 'react';

export default function HomePage() {
  const router = useRouter();
  
  useEffect(() => {
    // Redirect to custom agents page by default
    router.push('/custom');
  }, [router]);
  
  return null; // This page just redirects, no need to render anything
}