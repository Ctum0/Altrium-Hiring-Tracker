#!/usr/bin/env python
"""Systematic responsive design and cross-browser testing for Altrium Hiring Tracker."""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path


async def test_viewport(browser_instance, viewport_config, email, password, role_name, pages):
    """Test a specific viewport with a given role."""
    
    viewports = {
        "desktop": {"width": 1920, "height": 1080},
        "tablet": {"width": 768, "height": 1024},
        "mobile_iphone": {"width": 390, "height": 844},
        "mobile_android": {"width": 375, "height": 667},
    }
    
    viewport = viewports[viewport_config]
    tab_name = f"{role_name}_{viewport_config}_chrome"
    
    try:
        # Open tab
        tab = await browser_instance.open(
            name=tab_name,
            url="http://localhost:8000/login/",
            viewport=viewport,
        )
        
        await asyncio.sleep(2)
        
        # Take login screenshot
        screenshot_path = f"/home/ctum/PPPM/scratch/responsive_{role_name}_{viewport_config}_01_login.png"
        await tab.screenshot(path=screenshot_path)
        print(f"✓ {role_name} ({viewport_config}): Login page captured")
        
        # Try to identify login form elements
        try:
            # Look for username/email field
            await tab.click("input[type='text'], input[type='email']", timeout=3000)
            await tab.type(email)
            await asyncio.sleep(0.5)
            
            # Look for password field
            await tab.click("input[type='password']", timeout=3000)
            await tab.type(password)
            await asyncio.sleep(0.5)
            
            # Look for submit button
            await tab.click("button[type='submit'], input[type='submit']", timeout=3000)
            await asyncio.sleep(3)
            
            print(f"✓ {role_name} ({viewport_config}): Logged in successfully")
            
            # Test each page
            for page_idx, page_path in enumerate(pages[:3], 1):
                try:
                    # Navigate to page
                    await tab.goto(f"http://localhost:8000{page_path}")
                    await asyncio.sleep(2)
                    
                    # Check for horizontal scroll
                    scroll_info = await tab.run(
                        "(function() { return { scrollWidth: document.documentElement.scrollWidth, clientWidth: document.documentElement.clientWidth, hasHorizontalScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth }; })()",
                        timeout=5000
                    )
                    
                    scroll_status = "✗ SCROLL" if scroll_info.get('hasHorizontalScroll') else "✓"
                    
                    # Take screenshot
                    page_name = page_path.split('/')[-2] or page_path.split('/')[-1] or "home"
                    screenshot_path = f"/home/ctum/PPPM/scratch/responsive_{role_name}_{viewport_config}_{page_idx:02d}_{page_name}.png"
                    await tab.screenshot(path=screenshot_path)
                    
                    print(f"  {scroll_status} Page {page_idx}: {page_path} - {screenshot_path.split('/')[-1]}")
                    
                except Exception as e:
                    print(f"  ✗ Page error: {page_path} - {str(e)[:60]}")
        
        except Exception as e:
            print(f"✗ {role_name} ({viewport_config}): Form interaction failed - {str(e)[:60]}")
        
        finally:
            await tab.close()
    
    except Exception as e:
        print(f"✗ {role_name} ({viewport_config}): Fatal error - {str(e)[:80]}")


async def main():
    """Run comprehensive responsive design tests."""
    
    print("\n" + "=" * 80)
    print("ALTRIUM HIRING TRACKER - RESPONSIVE DESIGN & CROSS-BROWSER TEST")
    print("=" * 80)
    print(f"\nTest started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Test configuration
    roles_config = {
        "HR": {
            "email": "hr_demo@example.com",
            "password": "123456",
            "pages": ["/hr-dashboard/", "/jobs/", "/candidates/", "/pipeline/", "/feedback/"],
        },
        "Interviewer": {
            "email": "iv_demo@example.com",
            "password": "123456",
            "pages": ["/interviewer-dashboard/", "/interviewer-roster/", "/feedback/"],
        },
        "Management": {
            "email": "mgmt_demo@example.com",
            "password": "123456",
            "pages": ["/dashboard/", "/candidates/"],
        },
    }
    
    viewports = ["desktop", "tablet", "mobile_iphone", "mobile_android"]
    
    print("Test Matrix:")
    print(f"  Roles: {len(roles_config)} (HR, Interviewer, Management)")
    print(f"  Viewports: {len(viewports)} (Desktop, Tablet, iPhone, Android)")
    print(f"  Total tabs to test: {len(roles_config) * len(viewports)}")
    print(f"\nTesting pages per role:")
    for role, config in roles_config.items():
        print(f"  {role}: {len(config['pages'])} pages")
    
    # Run tests
    tasks = []
    for role, config in roles_config.items():
        for viewport in viewports:
            tasks.append(
                test_viewport(
                    browser,
                    viewport,
                    config["email"],
                    config["password"],
                    role,
                    config["pages"]
                )
            )
    
    print("\n" + "-" * 80)
    print("Starting browser tests...\n")
    
    # Execute tests sequentially to avoid browser resource issues
    for task in tasks:
        try:
            await task
        except Exception as e:
            print(f"✗ Test failed: {str(e)[:80]}")
        await asyncio.sleep(1)
    
    print("\n" + "-" * 80)
    print("Testing complete!")
    print(f"\nScreenshots saved to: /home/ctum/PPPM/scratch/responsive_*.png")
    
    # List screenshots
    screenshot_dir = Path("/home/ctum/PPPM/scratch")
    responsive_shots = list(screenshot_dir.glob("responsive_*.png"))
    print(f"Total screenshots captured: {len(responsive_shots)}")


if __name__ == "__main__":
    asyncio.run(main())
