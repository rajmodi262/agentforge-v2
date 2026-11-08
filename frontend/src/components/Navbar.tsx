import React, { useState, useEffect } from 'react';
import { NAV_LINKS } from '../utils/constants';

interface NavbarProps {
  scrollProgress: number;
}

export default function Navbar({ scrollProgress }: NavbarProps) {
  const isScrolled = scrollProgress > 0.02;

  return (
    <nav className={`navbar ${isScrolled ? 'navbar--scrolled' : ''}`}>
      <a href="#" className="navbar__logo">
        <div className="navbar__logo-icon">⚡</div>
        AgentForge
      </a>

      <div className="navbar__right">
        <ul className="navbar__links">
          {NAV_LINKS.map((link) => (
            <li key={link.label}>
              <a href={link.href} className="navbar__link">{link.label}</a>
            </li>
          ))}
        </ul>

        <MagneticNavBtn />
      </div>
    </nav>
  );
}

import { spacing, typography } from '../styles/tokens';

function MagneticNavBtn() {
  return (
    <a href="#launch" className="magnetic-btn" style={{ padding: `${spacing.sm} ${spacing.xl}`, fontSize: typography.sm }}>
      Launch Blueprint
    </a>
  );
}
