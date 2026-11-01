"use client";

import { useState } from 'react';
import { useRouter } from 'next/navigation';

export default function Home() {
  const [value, setValue] = useState<string>('');
  const [from, setFrom] = useState<'C' | 'F'>('C');
  const [result, setResult] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const inputValue = parseFloat(value);
    if (isNaN(inputValue) || !Number.isFinite(inputValue)) {
      setError('Invalid input');
      return;
    }
    try {
      const response = await fetch('/api/convert', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ value: inputValue, from }),
      });
      if (!response.ok) {
        const data = await response.json();
        setError(data.error);
        return;
      }
      const data = await response.json();
      setResult(data.result);
      setError(null);
    } catch (error) {
      setError('An error occurred while converting.');
    }
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setValue(e.target.value);
    setResult(null);
    setError(null);
  };

  const handleUnitChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setFrom(e.target.value as 'C' | 'F');
    setResult(null);
    setError(null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100vh' }}>
      <h1>Temperature Converter</h1>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <label htmlFor='value'>Value:</label>
        <input
          type='number'
          id='value'
          value={value}
          onChange={handleInputChange}
          required
          step='0.01'
        />
        <label htmlFor='from'>From:</label>
        <select id='from' value={from} onChange={handleUnitChange} required>
          <option value='C'>Celsius</option>
          <option value='F'>Fahrenheit</option>
        </select>
        <button type='submit'>Convert</button>
      </form>
      {result !== null && <p>Result: {result.toFixed(2)} {from === 'C' ? 'F' : 'C'}</p>}
      {error && <p style={{ color: 'red' }}>{error}</p>}
    </div>
  );
}