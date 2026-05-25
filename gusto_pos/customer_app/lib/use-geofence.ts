'use client';

import { useState, useCallback } from 'react';

// Haversine formula — returns distance in meters between two lat/lon points
function haversineDistance(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371000; // Earth's radius in meters
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export type GeofenceStatus = 'idle' | 'checking' | 'inside' | 'outside' | 'denied' | 'error';

interface UseGeofenceOptions {
  targetLat: number;
  targetLon: number;
  radiusMeters: number;
}

export function useGeofence({ targetLat, targetLon, radiusMeters }: UseGeofenceOptions) {
  const [status, setStatus] = useState<GeofenceStatus>('idle');
  const [distanceMeters, setDistanceMeters] = useState<number | null>(null);

  const checkLocation = useCallback((): Promise<GeofenceStatus> => {
    return new Promise((resolve) => {
      if (typeof navigator === 'undefined' || !navigator.geolocation) {
        setStatus('error');
        resolve('error');
        return;
      }

      setStatus('checking');
      setDistanceMeters(null);

      navigator.geolocation.getCurrentPosition(
        (position) => {
          const { latitude, longitude } = position.coords;
          const distance = haversineDistance(latitude, longitude, targetLat, targetLon);
          setDistanceMeters(Math.round(distance));
          const result: GeofenceStatus = distance <= radiusMeters ? 'inside' : 'outside';
          setStatus(result);
          resolve(result);
        },
        (err) => {
          // err.code: 1 = PERMISSION_DENIED, 2 = POSITION_UNAVAILABLE, 3 = TIMEOUT
          if (err.code === 1) {
            setStatus('denied');
            resolve('denied');
          } else {
            setStatus('error');
            resolve('error');
          }
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
      );
    });
  }, [targetLat, targetLon, radiusMeters]);

  const reset = useCallback(() => {
    setStatus('idle');
    setDistanceMeters(null);
  }, []);

  return { status, distanceMeters, checkLocation, reset };
}
