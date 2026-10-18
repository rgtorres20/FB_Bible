/**
 * Vercel Speed Insights initialization for FB Bible
 * 
 * This module initializes Speed Insights for the vanilla JavaScript frontend.
 * Speed Insights tracks Core Web Vitals and performance metrics.
 */

import { injectSpeedInsights } from '@vercel/speed-insights';

/**
 * Initialize Vercel Speed Insights
 * 
 * This function will:
 * - Inject the Speed Insights tracking script
 * - Enable debug mode in development
 * - Track performance metrics automatically
 */
export function initSpeedInsights() {
  // Check if we're in a browser environment
  if (typeof window === 'undefined') {
    return;
  }

  try {
    // Initialize Speed Insights with configuration
    const speedInsights = injectSpeedInsights({
      // Enable debug mode in development (disabled in production by default)
      debug: location.hostname === 'localhost' || location.hostname === '127.0.0.1',
      
      // Send all events by default (can be reduced to lower costs if needed)
      sampleRate: 1,
      
      // The route will be automatically detected from the URL
      // For single-page apps or dynamic routes, you can set this explicitly
    });

    if (speedInsights && location.hostname === 'localhost') {
      console.log('[Speed Insights] Initialized successfully (debug mode enabled)');
    }
  } catch (error) {
    // Fail silently in production, log in development
    if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
      console.error('[Speed Insights] Initialization failed:', error);
    }
  }
}

// Auto-initialize when the module is loaded
initSpeedInsights();
