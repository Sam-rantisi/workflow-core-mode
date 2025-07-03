n8n (pronounced "n-eight-n") is a free and open node-based workflow automation tool. Render is a unified platform to build and run all your apps and websites with free SSL, a global CDN, private networks and auto deploys from Git. Supabase is an open-source Firebase alternative that provides real-time database and authentication services. 

Here are the steps to deploy an n8n automation pack on Render and Supabase:

1. **Setup Supabase:**
    - Sign up for a free account on supabase.io.
    - Create a new project and note down the `SUPABASE_URL` and `SUPABASE_KEY`.

2. **Setup n8n:**
    - Install n8n on your local machine using npm: `npm install n8n -g`
    - Start n8n in your terminal: `n8n`
    - Open your browser and go to `http://localhost:5678/` to access the n8n editor.
    - Create your workflow and save it.

3. **Setup Render:**
    - Sign up for a free account on render.com.
    - Click on the "New Web Service" button.
    - Connect your GitHub or GitLab account and select your repository.
    - In the environment variables section, add the `SUPABASE_URL` and `SUPABase_KEY`.
    - Click on the "Save Web Service" button.

4. **Deploy n8n on Render:**
    - Create a Dockerfile in your project root directory with the following content:
        ```
        FROM n8nio/n8n

        COPY .n8n /root/.n8n

        CMD ["n8n", "start", "--tunnel"]
        ```
    - Push the Dockerfile to your Git repository.
    - Go to your Render dashboard and click on the "New Web Service" button.
    - Select your repository and branch.
    - In the environment section, add `N8N_BASIC_AUTH_ACTIVE=true`, `N8N_BASIC_AUTH_USER=<your_username>`, `N8N_BASIC_AUTH_PASSWORD=<your_password>`, `WEBHOOK_TUNNEL_URL=<your_render_service_url>`.
    - Click on the "Save Web Service" button.
    - Render will build and run your n8n service.

5. **Test your n8n workflow:**
    - Go to your Render service URL and login with your n8n username and password.
    - Click on your workflow and then on the "Execute Workflow" button.
    - Check if the workflow is running correctly.

Remember to replace `<your_username>`, `<your_password>`, and `<your_render_service_url>` with your actual username, password, and Render service URL. 

Please note that the instructions above are a basic guide and might need adjustments based on your specific n8n workflow and the configuration of your Render and Supabase services.