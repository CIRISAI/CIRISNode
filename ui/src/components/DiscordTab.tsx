"use client";
import React from "react";

export default function DiscordTab() {
  return (
    <div className="p-6 max-w-4xl mx-auto">
      <h2 className="text-2xl font-bold mb-4">Discord User Features</h2>
      <p className="mb-4">This section is available to users in the <span className="font-mono bg-gray-200 px-2 py-1 rounded">discord_user</span> group.</p>
      {/* Add Discord-specific features/components here */}
      <div className="bg-blue-50 border border-blue-200 rounded p-4 text-blue-900">
        <p>Welcome, Discord user! (Feature content goes here.)</p>
      </div>
    </div>
  );
}
