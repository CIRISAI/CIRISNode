'use client'
import { signIn } from 'next-auth/react'

export default function Login() {
  return (
    <div className="flex flex-col items-center justify-center min-h-screen space-y-2">
      <h1 className="text-2xl">Login</h1>
      <button className="px-4 py-2 bg-blue-500 text-white" onClick={() => signIn('google')}>
        Sign in with Google
      </button>
      <button className="px-4 py-2 bg-indigo-500 text-white" onClick={() => signIn('discord')}>
        Sign in with Discord
      </button>
    </div>
  )
}
